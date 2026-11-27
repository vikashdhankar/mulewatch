"""TF-IDF (word 1-2 grams + character 2-5 grams) + logistic regression."""
import pickle

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline


class TfidfLR:
    def __init__(self, params: dict, seed: int = 13):
        p = params
        self.pipe = Pipeline([
            ("features", FeatureUnion([
                ("word", TfidfVectorizer(analyzer="word", ngram_range=tuple(p.get("word_ngrams", [1, 2])),
                                         min_df=p.get("min_df", 2), sublinear_tf=True, lowercase=True,
                                         token_pattern=r"(?u)\[\w+\]|\b\w+\b")),
                ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=tuple(p.get("char_ngrams", [2, 5])),
                                         min_df=p.get("min_df", 2), sublinear_tf=True, lowercase=True,
                                         max_features=p.get("max_char_features", 200_000))),
            ])),
            ("clf", LogisticRegression(C=p.get("C", 4.0), max_iter=p.get("max_iter", 2000),
                                       class_weight=p.get("class_weight", "balanced"), random_state=seed)),
        ])

    def fit(self, texts, labels, dev_texts=None, dev_labels=None):
        self.pipe.fit(texts, labels)
        return self

    def predict(self, texts):
        return list(self.pipe.predict(texts)) if texts else []

    def save(self, path):
        with open(path, "wb") as f:
            pickle.dump(self.pipe, f)

    @classmethod
    def load(cls, path, params=None):
        m = cls(params or {})
        with open(path, "rb") as f:
            m.pipe = pickle.load(f)
        return m
