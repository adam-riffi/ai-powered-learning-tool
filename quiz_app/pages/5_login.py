"""Login page.

Handles three states:
1. OAuth callback  — code + provider in query params  -> exchange and redirect
2. Already logged in                                  -> show user info
3. Not logged in                                      -> show login buttons

Location: quiz_app/pages/5_login.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

from auth_guard import _render_login_buttons, load_user_from_callback, render_sidebar_user

st.set_page_config(page_title="Login", layout="centered")

load_user_from_callback()
render_sidebar_user()

user = st.session_state.get("user")

if user:
    st.title("You are logged in")
    cols = st.columns([1, 4])
    with cols[0]:
        if user.avatar:
            st.image(user.avatar, width=64)
    with cols[1]:
        st.markdown(f"### {user.name}")
        st.caption(user.email)
        st.caption(f"Provider: {user.provider}")

    st.divider()
    col_home, col_logout = st.columns(2)
    with col_home:
        if st.button("Go to home", use_container_width=True, type="primary"):
            st.switch_page("app.py")
    with col_logout:
        if st.button("Logout", use_container_width=True):
            st.session_state.clear()
            st.rerun()
    st.stop()

if st.session_state.get("oauth_error"):
    st.error(f"Authentication failed: {st.session_state.pop('oauth_error')}")

st.title("Login")
st.write("Sign in to access your courses, quizzes and flashcards.")
st.divider()

_render_login_buttons()
