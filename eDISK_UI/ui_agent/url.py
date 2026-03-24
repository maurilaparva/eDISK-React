"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: url.py
@Time: 7/15/25; 5:49 PM
"""
from django.urls import path
from . import views

urlpatterns = [
    path("", views.chat_page, name="chat_page"),
    path("api/chat", views.api_chat, name="api_chat"),
    path("api/progress/<str:run_id>", views.api_progress, name="api_progress"),
    path("api/recommendations", views.api_recommendations, name="api_recommendations"),
]