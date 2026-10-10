"""fuzzytitles: forgiving title search (typos, accents, missing words) on top of any DB."""
from .core import (normalize, search, significant_words, similarity, split_year)

__all__ = ["normalize", "search", "significant_words", "similarity", "split_year"]
__version__ = "0.1.0"
