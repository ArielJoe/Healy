import streamlit as st
from modules.healy import Healy
from azure.cosmos import CosmosClient
from dotenv import load_dotenv
from streamlit_cookies_manager import EncryptedCookieManager
import os
import bcrypt
import uuid
from datetime import datetime
import json
import pandas as pd

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
            "password_hash": password_hash.decode('utf-8'),
            "birthdate": birthdate,
            "weight": weight,
            "height": height,
            "created_at": datetime.utcnow().isoformat(),
            "last_login": None,
            "health_metrics": {
                "initial_weight": weight,
                "initial_height": height,
                "progress": []
            }
        }

        container.create_item(body=user_doc)
        return True
    except Exception as e:
        st.error(f"Registration failed: {str(e)}")
        return False

# Login user by verifying credentials using email
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
                "health_metrics": user.get("health_metrics", {})
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
    healy = Healy()
except Exception as e:
    st.error(f"Failed to initialize AI advisor: {str(e)}")
    st.stop()

# Initialize session state from cookies if available
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None
    
    if "user" in cookies:
        try:
            user_data = json.loads(cookies["user"])
            # Verify the user still exists in database
            query = "SELECT * FROM c WHERE c.id = @id"
            params = [{"name": "@id", "value": user_data["id"]}]
            users = list(container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            
            if users:
                st.session_state.user = user_data
                st.session_state.logged_in = True
        except:
            # Clear invalid cookie
            del cookies["user"]
            cookies.save()

# Sidebar for login/register
with st.sidebar:
    if st.session_state.logged_in:
        st.title(f"Welcome, {st.session_state.user['username']}!")
        
        # Display user health metrics
        st.subheader("Your Health Metrics")
        st.write(f"Birthdate: {st.session_state.user.get('birthdate', 'Not provided')}")
        st.write(f"Weight: {st.session_state.user.get('weight', 'Not provided')} kg")
        st.write(f"Height: {st.session_state.user.get('height', 'Not provided')} cm")
        
        if st.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.user = None
            del cookies["user"]
            cookies.save()
            st.rerun()
    else:
        st.title("User Authentication")
        auth_mode = st.radio("Choose Action", ["Login", "Register"], horizontal=True)

        if auth_mode == "Register":
            st.subheader("Create a new account")
            reg_username = st.text_input("Username", key="reg_username")
            reg_email = st.text_input("Email", key="reg_email")
            reg_password = st.text_input("Password", type="password", key="reg_password")
            reg_password_confirm = st.text_input("Confirm Password", type="password", key="reg_password_confirm")
            
            # Additional health metrics
            col1, col2 = st.columns(2)
            with col1:
                birthdate = st.date_input("Birthdate", min_value=datetime(1900, 1, 1), key="birthdate")
            with col2:
                weight = st.number_input("Weight (kg)", min_value=30.0, max_value=300.0, value=70.0, step=0.1, key="weight")
            
            height = st.number_input("Height (cm)", min_value=100.0, max_value=250.0, value=170.0, step=0.5, key="height")

            if st.button("Register", key="register_btn"):
                if reg_password != reg_password_confirm:
                    st.error("Passwords do not match.")
                elif reg_username and reg_email and reg_password:
                    if register_user(
                        reg_username, 
                        reg_email, 
                        reg_password,
                        birthdate.isoformat(),
                        weight,
                        height
                    ):
                        st.success("User registered successfully! Please login.")
                else:
                    st.error("Please fill all fields.")

        elif auth_mode == "Login":
            st.subheader("Login to your account")
            login_email = st.text_input("Email", key="login_email")
            login_password = st.text_input("Password", type="password", key="login_password")

            if st.button("Login", key="login_btn"):
                if login_user(login_email, login_password):
                    st.success(f"Welcome, {st.session_state.user['username']}!")
                    st.rerun()

# Main app content
if st.session_state.logged_in:
    st.title(f"AI Fitness Advisor")
    st.subheader(f"Hello, {st.session_state.user['username']}!")
    
    # Chat interface
    if "messages" not in st.session_state:
        st.session_state.messages = []
        st.session_state.messages.append({"role": "assistant", "content": "Hello! I'm your AI fitness advisor. How can I help you today?"})
    
    # Custom CSS for fixed bottom input and styling
    st.markdown("""
    <style>
        /* Make the main content area scrollable with padding for fixed input */
        .main .block-container {
            padding-bottom: 150px !important;
            max-height: calc(100vh - 150px);
            overflow-y: auto;
        }
        
        /* Fix the input container at the bottom */
        .fixed-bottom-input {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            z-index: 999;
            background: var(--background-color);
            border-top: 1px solid var(--secondary-background-color);
            padding: 1rem;
            backdrop-filter: blur(10px);
        }
        
        /* Hide the default file uploader label */
        .stFileUploader > label {
            display: none;
        }
        
        /* Style the upload button */
        .stFileUploader > div > div {
            padding: 0;
            border: none;
        }
        
        .stFileUploader > div > div > button {
            width: 60px;
            height: 47px;
            border-radius: 0.5rem;
            margin-left: 0.5rem;
        }
        
        /* Style the chat input container */
        .input-row {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            max-width: 100%;
        }
        
        .chat-input-wrapper {
            flex: 1;
        }
        
        /* Ensure chat messages are visible above the fixed input */
        .stChatMessage {
            margin-bottom: 1rem;
        }
        
        /* Adjust sidebar to account for fixed input */
        .css-1d391kg {
            padding-bottom: 120px;
        }
        
        /* Dark mode adjustments */
        @media (prefers-color-scheme: dark) {
            .fixed-bottom-input {
                background: rgba(14, 17, 23, 0.95);
                border-top-color: rgba(255, 255, 255, 0.1);
            }
        }
        
        /* Light mode adjustments */
        @media (prefers-color-scheme: light) {
            .fixed-bottom-input {
                background: rgba(255, 255, 255, 0.95);
                border-top-color: rgba(0, 0, 0, 0.1);
            }
        }
    </style>
    """, unsafe_allow_html=True)
    
    # Display chat messages in scrollable area
    chat_container = st.container()
    with chat_container:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
    
    # Create fixed bottom input using HTML container
    st.markdown('<div class="fixed-bottom-input">', unsafe_allow_html=True)
    
    # Chat input on top
    prompt = st.chat_input("Your fitness question", key="chat_input")
    
    # File upload below the text input
    uploaded_file = st.file_uploader(
        "📁 Upload a file (images, PDFs, text files)",
        type=["png", "jpg", "jpeg", "pdf", "txt"],
        key="file_uploader",
        help="Upload exercise photos, nutrition labels, workout plans, or progress images"
    )
    
    st.markdown('</div>', unsafe_allow_html=True)
            
    # Handle file upload
    if uploaded_file is not None:
        # Add file info to chat
        file_info = f"User uploaded a file: {uploaded_file.name} (type: {uploaded_file.type}, size: {uploaded_file.size} bytes)"
        st.session_state.messages.append({"role": "user", "content": file_info})
        
        # Process the file
        with st.spinner("Analyzing your file..."):
            try:
                response = f"📄 **File Received**: {uploaded_file.name}\n\n"
                response += "I can help you analyze:\n"
                response += "- Exercise form images\n"
                response += "- Nutrition labels\n"
                response += "- Workout plans\n"
                response += "- Progress photos\n\n"
                response += "What would you like me to focus on?"
            except Exception as e:
                response = f"Sorry, I encountered an error processing your file: {str(e)}"
        
        # Add assistant response to chat history
        st.session_state.messages.append({"role": "assistant", "content": response})
        st.rerun()
    
    # Handle chat input
    if prompt:
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # Generate AI response
        with st.spinner("Thinking..."):
            try:
                # Get user context
                user_context = {
                    "username": st.session_state.user['username'],
                    "birthdate": st.session_state.user.get('birthdate'),
                    "weight": st.session_state.user.get('weight'),
                    "height": st.session_state.user.get('height')
                }
                
                # Format the prompt with context
                contextual_prompt = f"""User profile:
- Username: {user_context['username']}
- Birthdate: {user_context['birthdate']}
- Weight: {user_context['weight']} kg
- Height: {user_context['height']} cm

User question: {prompt}"""
                
                response = healy.generate_response(contextual_prompt)
                
            except Exception as e:
                response = f"Sorry, I encountered an error processing your request: {str(e)}"
                st.error(f"Error details: {str(e)}")
        
        # Add assistant response to chat history
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
        - File upload for form analysis or nutrition tracking
    """)
    