from __future__ import annotations

import streamlit as st

from src.ui.api_client import ApiClient


@st.cache_resource(show_spinner=False)
def _default_client() -> ApiClient:
    return ApiClient.from_settings()


def get_client() -> ApiClient:
    """The API client of this process. Tests replace this function with one returning a fake."""
    return _default_client()
