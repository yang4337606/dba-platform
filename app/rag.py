"""
RAG 向量检索模块

使用简化的 TF-IDF 向量化实现相似案例检索
如需更强大的语义匹配，可替换为 sentence-transformers
"""

import json
import math
import time
import threading
from collections import Counter
import re


class SimpleVectorizer:
    """简化的 TF-IDF 向量化器"""

    def __init__(self):
        self.vocabulary = set()
        self.idf = {}

    def tokenize(self, text):
        """简单分词"""
        if not text:
            return []
        # 移除标点，转小写，分词
        text = re.sub(r'[^\w\s]', ' ', text.lower())
        tokens = text.split()
        return [t for t in tokens if len(t) > 1]

    def fit(self, documents):
        """训练 IDF"""
        doc_count = len(documents)
        if doc_count == 0:
            return

        # 统计每个词出现在多少文档中
        doc_freq = Counter()
        for doc in documents:
            tokens = set(self.tokenize(doc))
            self.vocabulary.update(tokens)
            for token in tokens:
                doc_freq[token] += 1

        # 计算 IDF
        for token, freq in doc_freq.items():
            self.idf[token] = math.log(doc_count / freq)

    def vectorize(self, text):
        """将文本转换为向量"""
        tokens = self.tokenize(text)
        if not tokens:
            return {}

        # 计算 TF
        tf = Counter(tokens)
        total = len(tokens)

        # 计算 TF-IDF
        vector = {}
        for token, count in tf.items():
            if token in self.idf:
                vector[token] = (count / total) * self.idf[token]

        return vector

    def cosine_similarity(self, vec1, vec2):
        """计算余弦相似度"""
        if not vec1 or not vec2:
            return 0.0

        # 计算点积
        common_keys = set(vec1.keys()) & set(vec2.keys())
        dot_product = sum(vec1[k] * vec2[k] for k in common_keys)

        # 计算模
        norm1 = math.sqrt(sum(v ** 2 for v in vec1.values()))
        norm2 = math.sqrt(sum(v ** 2 for v in vec2.values()))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)


class RAGRetriever:
    """RAG 检索器"""

    def __init__(self, db):
        self.db = db
        self.vectorizer = SimpleVectorizer()
        self.index = {}  # {record_id: vector}
        self._last_build = 0
        self._ttl = 1800  # 索引有效期 30 分钟（减少重建频率）
        self._lock = threading.Lock()
        self._build_index()

    def _build_index(self):
        """构建索引，缓存 _prepare_text 结果避免重复计算"""
        records = self.db.get_all_history(limit=1000)

        if not records:
            return

        # 预计算文本，避免 _prepare_text 被调用两次
        prepared = []
        for record in records:
            text = self._prepare_text(record)
            prepared.append((record, text))

        # 训练向量化器
        self.vectorizer.fit([text for _, text in prepared])

        # 构建索引
        self.index = {}
        for record, text in prepared:
            vector = self.vectorizer.vectorize(text)
            self.index[record['id']] = {
                'vector': vector,
                'record': record
            }

        self._last_build = time.time()

    def _ensure_fresh(self):
        """检查索引是否过期，过期则重建"""
        if time.time() - self._last_build > self._ttl:
            self._build_index()

    def add_record(self, record):
        """增量添加一条记录到索引（无需全量重建）"""
        if not record or not record.get('id'):
            return
        text = self._prepare_text(record)
        vector = self.vectorizer.vectorize(text)
        with self._lock:
            self.index[record['id']] = {
                'vector': vector,
                'record': record
            }

    def _prepare_text(self, record):
        """准备用于向量化的文本"""
        parts = []

        if record.get('main_problem'):
            parts.append(record['main_problem'])

        if record.get('diagnosis_summary'):
            parts.append(record['diagnosis_summary'])

        if record.get('load_type'):
            parts.append(record['load_type'])

        return ' '.join(parts)

    def search(self, query, limit=5, min_similarity=0.1):
        """搜索相似案例"""
        self._ensure_fresh()

        query_vector = self.vectorizer.vectorize(query)
        if not query_vector:
            return []

        # Take a snapshot under lock to avoid iteration issues
        with self._lock:
            index_snapshot = dict(self.index)

        if not index_snapshot:
            return []

        similarities = []
        for record_id, data in index_snapshot.items():
            similarity = self.vectorizer.cosine_similarity(query_vector, data['vector'])
            if similarity >= min_similarity:
                similarities.append({
                    'record': data['record'],
                    'similarity': similarity
                })

        similarities.sort(key=lambda x: x['similarity'], reverse=True)
        return similarities[:limit]

    def search_by_record(self, record_id, limit=5):
        """根据记录ID搜索相似案例"""
        self._ensure_fresh()

        if record_id not in self.index:
            return []

        query_vector = self.index[record_id]['vector']

        # 计算相似度
        similarities = []
        for rid, data in self.index.items():
            if rid == record_id:
                continue

            similarity = self.vectorizer.cosine_similarity(query_vector, data['vector'])
            if similarity > 0:
                similarities.append({
                    'record': data['record'],
                    'similarity': similarity
                })

        # 排序并返回
        similarities.sort(key=lambda x: x['similarity'], reverse=True)
        return similarities[:limit]


# 全局检索器实例（延迟初始化，线程安全）
_retriever = None
_retriever_lock = threading.Lock()


def get_retriever(db):
    """获取检索器实例"""
    global _retriever
    if _retriever is None:
        with _retriever_lock:
            if _retriever is None:
                _retriever = RAGRetriever(db)
    return _retriever


def rebuild_index(db):
    """重建索引"""
    global _retriever
    with _retriever_lock:
        _retriever = RAGRetriever(db)
