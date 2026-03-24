"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: build_faiss_index.py
@Time: 10/16/25; 11:02 AM
"""
# ui_agent/management/commands/build_faiss_index.py
from django.core.management.base import BaseCommand
from ui_agent.services.index_builder import build_faiss


class Command(BaseCommand):
    help = "Build FAISS index from SQLite entity_embeddings"

    def handle(self, *args, **kwargs):
        n, dim = build_faiss()
        self.stdout.write(self.style.SUCCESS(f"Built FAISS with {n} vectors, dim={dim}"))
