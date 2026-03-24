
from ui_agent.services import faiss_index
index, meta = faiss_index.load_index()
print("✅ FAISS ready:", len(meta))

