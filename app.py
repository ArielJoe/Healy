import streamlit as st
from modules.healy import Healy # Assuming this is your custom module
from azure.cosmos import CosmosClient
from dotenv import load_dotenv
from streamlit_cookies_manager import EncryptedCookieManager
import os
import bcrypt
import uuid
from datetime import datetime
import json
import pandas as pd
import io

# Load environment variables
load_dotenv()

# Initialize Streamlit page
st.set_page_config(page_title="Healy", layout="wide")

# Initialize cookies
cookies = EncryptedCookieManager(
    prefix="healy/",
    password=os.getenv("COOKIE_PASSWORD", "default-cookie-password")
)

if not cookies.ready():
    # Wait for cookies to be ready
    st.spinner("Loading session...")
    st.stop()

# Initialize Cosmos client
try:
    client = CosmosClient(os.getenv("COSMOS_URI"), credential=os.getenv("COSMOS_KEY"))
    database = client.get_database_client(os.getenv("DATABASE_NAME"))
    container = database.get_container_client(os.getenv("CONTAINER_NAME"))
except Exception as e:
    st.error(f"Failed to connect to database: {str(e)}")
    st.stop()

# Password hashing functions
def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

def check_password(password: str, hashed: bytes) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed)

# Register a new user with additional health metrics
def register_user(username: str, email: str, password: str, birthdate: str, weight: float, height: float) -> bool:
    try:
        # Check if username or email already exists
        query = "SELECT * FROM c WHERE c.username = @username OR c.email = @email"
        params = [
            {"name": "@username", "value": username},
            {"name": "@email", "value": email}
        ]
        existing_users = list(container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        ))
        
        if existing_users:
            st.error("Username or email already exists.")
            return False

        # Hash the password
        password_hash = hash_password(password)

        # Create user document with health metrics
        user_doc = {
            "id": str(uuid.uuid4()),
            "username": username,
            "email": email,
            "password_hash": password_hash.decode('utf-8'), # Store as string
            "birthdate": birthdate,
            "weight": weight,
            "height": height,
            "created_at": datetime.utcnow().isoformat(),
            "last_login": None,
            "health_metrics": {
                "initial_weight": weight,
                "initial_height": height,
                "progress": [] # To store historical data like [(date, weight), ...]
            }
        }

        container.create_item(body=user_doc)
        return True
    except Exception as e:
        st.error(f"Registration failed: {str(e)}")
        return False

def process_csv_file(uploaded_file):
    """Process uploaded CSV file and return DataFrame and summary"""
    try:
        # Read CSV file
        df = pd.read_csv(uploaded_file)
        
        # Get basic info about the CSV
        csv_info = {
            "filename": uploaded_file.name,
            "shape": df.shape,
            "columns": df.columns.tolist(),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.to_dict().items()}, # ensure serializable
            "head": df.head().to_dict('records'),
            "null_counts": {col: int(count) for col, count in df.isnull().sum().to_dict().items()}, # ensure serializable
            "summary_stats": df.describe(include='all').to_dict() if not df.empty else {} # include all, ensure serializable
        }
        
        return df, csv_info
    except Exception as e:
        st.error(f"Error processing CSV file: {str(e)}")
        return None, None

def format_csv_for_prompt(df, csv_info, user_question=""):
    """Format CSV data for AI prompt"""
    # Ensure data types are strings for the prompt
    dtypes_str = "\n".join([f"- {col}: {dtype}" for col, dtype in csv_info['dtypes'].items()])
    missing_values_str = "\n".join([f"- {col}: {count} missing" for col, count in csv_info['null_counts'].items() if count > 0]) or "No missing values"
    
    # Handle potentially large summary_stats by converting to string representation
    summary_stats_str = ""
    if csv_info['summary_stats']:
        try:
            summary_stats_df = pd.DataFrame(csv_info['summary_stats'])
            summary_stats_str = f"Summary Statistics:\n{summary_stats_df.to_string()}"
        except Exception:
            summary_stats_str = f"Summary Statistics (raw):\n{json.dumps(csv_info['summary_stats'], indent=2)}"


    prompt_text = f"""
CSV File Analysis Request:

File: {csv_info['filename']}
Shape: {csv_info['shape'][0]} rows × {csv_info['shape'][1]} columns
Columns: {', '.join(csv_info['columns'])}

Data Preview (first 5 rows):
{pd.DataFrame(csv_info['head']).to_string(index=False)}

Data Types:
{dtypes_str}

Missing Values:
{missing_values_str}

{summary_stats_str}

User Question: {user_question}

Please analyze this data and provide insights based on the user's question. If it's fitness/health related data, provide relevant recommendations.
"""
    return prompt_text

def login_user(email: str, password: str) -> bool:
    try:
        query = "SELECT * FROM c WHERE c.email = @email"
        params = [{"name": "@email", "value": email}]
        users = list(container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        ))
        
        if not users:
            st.error("User not found.")
            return False

        user = users[0]
        stored_hash = user.get("password_hash", "").encode('utf-8')

        if check_password(password, stored_hash):
            # Update last login time
            user["last_login"] = datetime.utcnow().isoformat()
            container.upsert_item(user)
            
            # Store user info including health metrics
            user_data = {
                "id": user.get("id"),
                "username": user.get("username"),
                "email": user.get("email"),
                "birthdate": user.get("birthdate"),
                "weight": user.get("weight"),
                "height": user.get("height"),
                "health_metrics": user.get("health_metrics", {
                    "initial_weight": user.get("weight"), # ensure these are populated if missing
                    "initial_height": user.get("height"),
                    "progress": []
                })
            }
            st.session_state.user = user_data
            st.session_state.logged_in = True
            
            # Set cookie
            cookies["user"] = json.dumps(user_data)
            cookies.save()
            return True
        else:
            st.error("Incorrect password.")
            return False
    except Exception as e:
        st.error(f"Login failed: {str(e)}")
        return False

# Initialize AI fitness advisor
try:
    healy = Healy() # Make sure Healy class is defined or imported
except Exception as e:
    st.error(f"Failed to initialize AI advisor: {str(e)}")
    st.stop()

# Initialize session state from cookies if available
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None
    
    if "user" in cookies:
        try:
            user_data_str = cookies["user"]
            if user_data_str: # Check if cookie is not empty
                user_data = json.loads(user_data_str)
                # Verify the user still exists in database
                query = "SELECT * FROM c WHERE c.id = @id"
                params = [{"name": "@id", "value": user_data["id"]}]
                db_users = list(container.query_items(
                    query=query,
                    parameters=params,
                    enable_cross_partition_query=True
                ))
                
                if db_users:
                    # Refresh session state with potentially updated data from DB (optional, or merge)
                    db_user = db_users[0]
                    st.session_state.user = { # Ensure all fields are present
                        "id": db_user.get("id"),
                        "username": db_user.get("username"),
                        "email": db_user.get("email"),
                        "birthdate": db_user.get("birthdate"),
                        "weight": db_user.get("weight"),
                        "height": db_user.get("height"),
                        "health_metrics": db_user.get("health_metrics", {
                            "initial_weight": db_user.get("weight"),
                            "initial_height": db_user.get("height"),
                            "progress": []
                        })
                    }
                    st.session_state.logged_in = True
                else: # User not in DB, clear cookie
                    del cookies["user"]
                    cookies.save()
        except json.JSONDecodeError:
            st.warning("Invalid user session cookie. Please login again.")
            if "user" in cookies:
                del cookies["user"]
                cookies.save()
        except Exception as e: # Catch other potential errors during cookie load
            st.warning(f"Error loading session: {str(e)}. Please login again.")
            if "user" in cookies:
                del cookies["user"]
                cookies.save()


# Sidebar for login/register
with st.sidebar:
    if st.session_state.logged_in and st.session_state.user: # Ensure user data exists
        st.title(f"Welcome, {st.session_state.user['username']}!")
        
        # Display user health metrics
        st.subheader("Your Health Metrics")
        st.write(f"Birthdate: {st.session_state.user.get('birthdate', 'Not provided')}")
        st.write(f"Weight: {st.session_state.user.get('weight', 'Not provided')} kg")
        st.write(f"Height: {st.session_state.user.get('height', 'Not provided')} cm")
        
        if st.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.user = None
            if "user" in cookies: # Check before deleting
                del cookies["user"]
                cookies.save()
            # Clear other relevant session state if needed
            st.session_state.messages = [] 
            st.session_state.csv_data = None
            st.session_state.csv_info = None
            st.session_state.last_uploaded_file_id = None # Reset this on logout
            st.rerun()
    else:
        st.title("User Authentication")
        auth_mode = st.radio("Choose Action", ["Login", "Register"], horizontal=True, key="auth_mode_radio")

        if auth_mode == "Register":
            st.subheader("Create a new account")
            with st.form("register_form"):
                reg_username = st.text_input("Username", key="reg_username")
                reg_email = st.text_input("Email", key="reg_email")
                reg_password = st.text_input("Password", type="password", key="reg_password")
                reg_password_confirm = st.text_input("Confirm Password", type="password", key="reg_password_confirm")
                
                # Additional health metrics
                col1, col2 = st.columns(2)
                with col1:
                    birthdate = st.date_input("Birthdate", min_value=datetime(1900, 1, 1), value=None, key="birthdate")
                with col2:
                    weight = st.number_input("Weight (kg)", min_value=10.0, max_value=500.0, value=70.0, step=0.1, key="weight")
                
                height = st.number_input("Height (cm)", min_value=50.0, max_value=300.0, value=170.0, step=0.5, key="height")
                
                submitted_register = st.form_submit_button("Register")

                if submitted_register:
                    if not all([reg_username, reg_email, reg_password, reg_password_confirm, birthdate]):
                        st.error("Please fill all mandatory fields (Username, Email, Password, Birthdate).")
                    elif reg_password != reg_password_confirm:
                        st.error("Passwords do not match.")
                    else:
                        if register_user(
                            reg_username, 
                            reg_email, 
                            reg_password,
                            birthdate.isoformat(),
                            weight,
                            height
                        ):
                            st.success("User registered successfully! Please switch to Login.")
                        # Errors from register_user are handled within the function via st.error

        elif auth_mode == "Login":
            st.subheader("Login to your account")
            with st.form("login_form"):
                login_email = st.text_input("Email", key="login_email")
                login_password = st.text_input("Password", type="password", key="login_password")
                submitted_login = st.form_submit_button("Login")

                if submitted_login:
                    if login_user(login_email, login_password):
                        st.success(f"Welcome, {st.session_state.user['username']}!")
                        st.rerun()
                    # Errors from login_user are handled within the function via st.error

# Main app content
if st.session_state.logged_in and st.session_state.user:
    st.title(f"AI Fitness Advisor")
    st.subheader(f"Hello, {st.session_state.user['username']}!")
    
    # Chat interface with CSV storage
    if "messages" not in st.session_state:
        st.session_state.messages = []
        st.session_state.messages.append({"role": "assistant", "content": "Hello! I'm your AI fitness advisor. How can I help you today?"})
    
    # Initialize CSV data storage
    if "csv_data" not in st.session_state:
        st.session_state.csv_data = None
        st.session_state.csv_info = None

    # Initialize tracking for acknowledged file upload
    if "last_uploaded_file_id" not in st.session_state:
        st.session_state.last_uploaded_file_id = None
    
    # Custom CSS for fixed bottom input and styling
    st.markdown("""
    <style>
        /* Make the main content area scrollable with padding for fixed input */
        .main .block-container {
            padding-bottom: 180px !important; /* Increased padding for file uploader */
            /* max-height: calc(100vh - 180px); Consider if needed, might conflict */
            /* overflow-y: auto; This might be handled by Streamlit's chat elements better */
        }
        
        /* Fix the input container at the bottom */
        .fixed-bottom-input {
            position: fixed;
            bottom: 0;
            left: 0; /* Adjust if sidebar exists and is not overlaid */
            right: 0;
            z-index: 999;
            background: var(--background-color); /* Use Streamlit theme variables */
            border-top: 1px solid var(--secondary-background-color);
            padding: 1rem;
            /* backdrop-filter: blur(10px); /* Optional: for frosted glass effect */
        }
        
        /* Style the file uploader within the fixed input */
        .fixed-bottom-input .stFileUploader > label {
            font-size: 0.875rem; /* Smaller label */
            color: var(--text-color);
            margin-bottom: 0.25rem; /* Reduced margin */
        }
        
        .fixed-bottom-input .stFileUploader > div > div > button { /* Target the button inside */
            width: 100%;
            /* height: 30px; /* Adjust button height if needed */
            /* border-radius: 0.5rem; */
            /* margin: 0; */
        }
        
        /* Ensure chat messages are visible above the fixed input */
        .stChatMessage {
            margin-bottom: 1rem;
        }
        
        /* Adjust sidebar to account for fixed input if it's not an overlay sidebar */
        /* .css-1d391kg { /* Default Streamlit sidebar class, may change */
        /* padding-bottom: 180px; /* Match fixed input height */
        /* } */
        
        /* Dark mode adjustments */
        @media (prefers-color-scheme: dark) {
            .fixed-bottom-input {
                background: rgba(14, 17, 23, 0.95); /* Darker, slightly transparent */
                border-top-color: rgba(255, 255, 255, 0.1);
            }
        }
        
        /* Light mode adjustments */
        @media (prefers-color-scheme: light) {
            .fixed-bottom-input {
                background: rgba(255, 255, 255, 0.95); /* Lighter, slightly transparent */
                border-top-color: rgba(0, 0, 0, 0.1);
            }
        }
    </style>
    """, unsafe_allow_html=True)
    
    # Display current CSV info if available
    if st.session_state.csv_data is not None and st.session_state.csv_info:
        with st.expander(f"📊 Loaded CSV: {st.session_state.csv_info.get('filename', 'Unknown File')}", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                shape = st.session_state.csv_info.get('shape', (0,0))
                st.write(f"**Shape:** {shape[0]} rows × {shape[1]} columns")
                st.write(f"**Columns:** {', '.join(st.session_state.csv_info.get('columns', []))}")
            with col2:
                if st.button("🗑️ Clear CSV Data", key="clear_csv"):
                    st.session_state.csv_data = None
                    st.session_state.csv_info = None
                    st.session_state.last_uploaded_file_id = None # Also clear this if CSV is manually cleared
                    st.rerun()
            
            # Show data preview
            st.write("**Data Preview:**")
            st.dataframe(st.session_state.csv_data.head(), use_container_width=True)

    # Display chat messages in scrollable area
    chat_container = st.container() # This will be the scrollable message area
    with chat_container:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
    
    # Create fixed bottom input using HTML container
    st.markdown('<div class="fixed-bottom-input">', unsafe_allow_html=True)
    
    # Chat input on top
    prompt = st.chat_input("Your fitness question or CSV query", key="chat_input")
    
    # File upload below the text input
    uploaded_file = st.file_uploader(
        "📁 Upload: CSV for data analysis, or images/PDFs/text for general queries",
        type=["csv", "png", "jpg", "jpeg", "pdf", "txt"],
        key="file_uploader", # Using a key helps maintain state a bit better
        help="Upload CSV data, exercise photos, nutrition labels, workout plans, or progress images"
    )
    
    st.markdown('</div>', unsafe_allow_html=True)
            
    # Handle file upload - THIS IS THE CORRECTED SECTION
    if uploaded_file is not None:
        current_file_id = uploaded_file.file_id

        # Only process if it's a new file upload event (different file_id)
        if st.session_state.last_uploaded_file_id != current_file_id:
            st.session_state.last_uploaded_file_id = current_file_id # Update to current file_id

            if uploaded_file.type == "text/csv":
                with st.spinner("Processing CSV file..."):
                    # Reset previous CSV data if a new CSV is uploaded
                    st.session_state.csv_data = None 
                    st.session_state.csv_info = None
                    df, csv_info_dict = process_csv_file(uploaded_file) # Renamed to avoid conflict
                    
                    if df is not None and csv_info_dict is not None:
                        st.session_state.csv_data = df
                        st.session_state.csv_info = csv_info_dict # Store the dict
                        
                        csv_summary = f"📊 **CSV File Uploaded**: {csv_info_dict['filename']}\n\n"
                        csv_summary += f"**Data Overview:**\n"
                        csv_summary += f"- Shape: {csv_info_dict['shape'][0]} rows × {csv_info_dict['shape'][1]} columns\n"
                        csv_summary += f"- Columns: {', '.join(csv_info_dict['columns'])}\n\n"
                        csv_summary += "Your CSV data is now loaded! You can ask me questions about this data. For example:\n"
                        csv_summary += "- 'Analyze my workout data'\n"
                        csv_summary += "- 'Show me trends in my fitness metrics'\n"
                        csv_summary += "- 'Create a summary of my progress based on the CSV'"
                        
                        st.session_state.messages.append({"role": "assistant", "content": csv_summary})
                        st.rerun() # Rerun to display the message and update UI
                    else:
                        st.session_state.last_uploaded_file_id = None # Reset if processing failed
            else:
                # For non-CSV, clear any existing CSV data to avoid confusion
                if st.session_state.csv_data is not None:
                    st.toast("Note: Non-CSV file uploaded. Previous CSV data has been cleared for this chat.")
                    st.session_state.csv_data = None
                    st.session_state.csv_info = None

                file_info_msg = f"User uploaded a file: {uploaded_file.name} (type: {uploaded_file.type}, size: {uploaded_file.size} bytes)"
                st.session_state.messages.append({"role": "user", "content": file_info_msg})
                
                with st.spinner("Preparing file information..."):
                    try:
                        # This is a placeholder. Actual analysis of non-CSV will happen if the user asks.
                        response = f"📄 **File Received**: {uploaded_file.name}\n\n"
                        response += "I've noted the file. You can ask me questions about it. For example:\n"
                        if uploaded_file.type.startswith("image/"):
                            response += "- 'Analyze the form in this exercise photo.'\n"
                            response += "- 'What food is this (from image)? Estimate calories.'"
                        elif uploaded_file.type == "application/pdf":
                            response += "- 'Summarize this PDF document.'\n"
                            response += "- 'Extract key points from my workout plan PDF.'"
                        elif uploaded_file.type == "text/plain":
                            response += "- 'What are the main topics in this text file?'"
                        response += "\nWhat would you like me to focus on regarding this file?"
                    except Exception as e:
                        response = f"Sorry, I encountered an error noting your file: {str(e)}"
                
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.rerun() # Rerun to display the message
        # If last_uploaded_file_id IS THE SAME as current_file_id, it means we've already
        # acknowledged this specific upload instance in an immediately preceding script run.
        # So, we do nothing here to prevent re-adding the acknowledgment.
        # The app will now wait for the user's `prompt`.

    # Handle chat input
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.spinner("Thinking..."):
            try:
                user_context = {
                    "username": st.session_state.user['username'],
                    "birthdate": st.session_state.user.get('birthdate'),
                    "weight": st.session_state.user.get('weight'),
                    "height": st.session_state.user.get('height'),
                    "health_metrics": st.session_state.user.get('health_metrics')
                }
                
                contextual_prompt_parts = [f"User profile:\n- Username: {user_context['username']}"]
                if user_context['birthdate']:
                    contextual_prompt_parts.append(f"- Birthdate: {user_context['birthdate']}")
                if user_context['weight']:
                    contextual_prompt_parts.append(f"- Weight: {user_context['weight']} kg")
                if user_context['height']:
                    contextual_prompt_parts.append(f"- Height: {user_context['height']} cm")
                if user_context['health_metrics']:
                     contextual_prompt_parts.append(f"- Health Metrics: {json.dumps(user_context['health_metrics'])}")


                if st.session_state.csv_data is not None and st.session_state.csv_info is not None:
                    # If CSV is loaded, assume the prompt might be about it.
                    # The format_csv_for_prompt function now includes the user_question (prompt).
                    csv_analysis_request = format_csv_for_prompt(
                        st.session_state.csv_data, 
                        st.session_state.csv_info, 
                        prompt # Pass the user's actual question here
                    )
                    contextual_prompt_parts.append(f"\n{csv_analysis_request}")
                else:
                    # Regular prompt without CSV data, or if the user is asking about a generic uploaded file
                    contextual_prompt_parts.append(f"\nUser question: {prompt}")
                    # If a non-CSV file was just uploaded, we could add a note here, but
                    # the AI should ideally use the chat history which includes the file upload message.

                final_contextual_prompt = "\n".join(contextual_prompt_parts)
                
                # For non-CSV files, the AI needs to be instructed to look at the chat history
                # if the prompt refers to a previously mentioned file.
                # The `Healy` class's `generate_response` would need to handle chat history.
                # For now, we're passing the file context (if CSV) or just the prompt.
                # If you have a non-CSV file uploaded, you might need a different call to healy or
                # ensure healy.generate_response can use st.session_state.messages for context.
                # The placeholder "response" for non-CSV files above only acknowledges.
                # The actual analysis of non-CSV files based on a subsequent prompt is not yet fully implemented here.
                # It would require `healy.generate_response` to potentially accept image/pdf/text data or use a multimodal model.

                response = healy.generate_response(final_contextual_prompt) # Assuming Healy can take history
                
            except Exception as e:
                response = f"Sorry, I encountered an error processing your request: {str(e)}"
                st.error(f"Error details: {str(e)}") # Log error for debugging
        
        st.session_state.messages.append({"role": "assistant", "content": response})
        st.rerun()
        
else:
    st.title("AI Fitness Advisor")
    st.markdown("""
        ## Welcome to Healy!
        
        Please login or register in the sidebar to get personalized fitness advice.
        
        Features:
        - Personalized workout plans
        - Nutrition guidance
        - Progress tracking
        - 24/7 AI fitness coaching
        - File upload for form analysis, nutrition tracking (CSV, images, PDFs), and more!
    """)
    