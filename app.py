import streamlit as st
from modules.healy import Healy
from azure.cosmos import CosmosClient, exceptions
from dotenv import load_dotenv
from streamlit_cookies_manager import EncryptedCookieManager
import os
import bcrypt
import uuid
from datetime import datetime
import json

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

# Register a new user
def register_user(username: str, email: str, password: str) -> bool:
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

        # Create user document
        user_doc = {
            "id": str(uuid.uuid4()),
            "username": username,
            "email": email,
            "password_hash": password_hash.decode('utf-8'),
            "created_at": datetime.utcnow().isoformat(),
            "last_login": None
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
            
            # Store user info
            user_data = {
                "id": user.get("id"),
                "username": user.get("username"),
                "email": user.get("email")
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

            if st.button("Register", key="register_btn"):
                if reg_password != reg_password_confirm:
                    st.error("Passwords do not match.")
                elif reg_username and reg_email and reg_password:
                    if register_user(reg_username, reg_email, reg_password):
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
    
    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Chat input
    if prompt := st.chat_input("Your fitness question"):
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Generate AI response
        with st.spinner("Thinking..."):
            try:
                response = healy.generate_response(prompt)
            except Exception as e:
                response = f"Sorry, I encountered an error: {str(e)}"
        
        # Display assistant response
        with st.chat_message("assistant"):
            st.markdown(response)
        
        # Add assistant response to chat history
        st.session_state.messages.append({"role": "assistant", "content": response})
else:
    st.title("Welcome to Healy!")
    st.markdown("""
        Please login or register in the sidebar to get personalized fitness advice.
        
        Features:
        - Personalized workout plans
        - Nutrition guidance
        - Progress tracking
        - 24/7 AI fitness coaching
    """)
    