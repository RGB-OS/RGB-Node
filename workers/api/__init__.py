"""
API client module for communicating with FastAPI service.
"""
from workers.api.client import APIClient, get_api_client

__all__ = ['APIClient', 'get_api_client']

