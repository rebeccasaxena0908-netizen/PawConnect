"""
The Streamlit side of PawConnectClient.

Each browser session gets its own client; the sign-in token lives in
st.session_state.token, so it survives reruns but not a closed tab.
"""
from __future__ import annotations

import streamlit as st

from api.client import ApiError, AuthError, PawConnectClient  # noqa: F401 (re-exported for the dashboards)
from core.models import User


def api() -> PawConnectClient:
    client = st.session_state.get("api_client")
    if client is None:
        client = PawConnectClient()            # PAWCONNECT_MODE decides: HTTP API or in-process
        st.session_state.api_client = client
    client.token = st.session_state.get("token")
    return client


def sign_in(reply_user: dict) -> None:
    """Remember the token the client just received (read it directly – api() would overwrite it)."""
    st.session_state.token = st.session_state.api_client.token
    st.session_state.user = reply_user


def sign_out(message: str = "") -> None:
    st.session_state.token = None
    st.session_state.user = None
    if message:
        st.session_state.flash = message


def current_user() -> User | None:
    """The signed-in user as a core.models.User (re-read from /me so role changes apply)."""
    if not st.session_state.get("token"):
        return None
    try:
        data = api().me()
    except AuthError as error:
        sign_out(error.message)
        return None
    return User.from_dict(data)
