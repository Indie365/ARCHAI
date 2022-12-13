# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Word-based tokenizer.
"""

import os
from collections import Counter, OrderedDict
from typing import List, Optional

from overrides import overrides

from archai.common import utils
from archai.nlp import logging_utils
from archai.nlp.datasets.nvidia import distributed_utils
from archai.nlp.datasets.nvidia.tokenizer_utils.special_token_enum import (
    SpecialTokenEnum,
)
from archai.nlp.datasets.nvidia.tokenizer_utils.token_config import TokenConfig
from archai.nlp.datasets.nvidia.tokenizer_utils.vocab_base import VocabBase

logger = logging_utils.get_logger(__name__)


class WordVocab(VocabBase):
    """Implements a word-based vocabulary/tokenizer."""

    def __init__(
        self,
        save_path: str,
        vocab_size: Optional[int] = None,
        bos_token: Optional[str] = None,
        eos_token: Optional[str] = "<eos>",
        unk_token: Optional[str] = "<unk>",
        min_frequency: Optional[int] = 0,
        lower_case: Optional[int] = False,
        delimiter: Optional[str] = None,
        encode_special_tokens: Optional[bool] = True,
        decode_special_tokens: Optional[bool] = True,
    ):
        """Defines the tokenization pipeline.

        Args:
            save_path: Path to save the vocabulary.
            vocab_size: Maximum size of vocabulary.
            bos_token: Begin-of-sentence token.
            eos_token: End-of-sentence token.
            unk_token: Unknown token.
            min_frequency: Minimum frequency of tokens.
            model_max_length: Maximum length of sequence.
            lower_case: Whether lower case should be applied.
            delimiter: Delimiter between tokens.
            encode_special_tokens: Whether special tokens should be encoded.
            decode_special_tokens: Whether special tokens should be decoded.

        """

        self.counter = Counter()

        # No prefix space or line needed as we delimit on white space unlike in bbpe
        self._config = TokenConfig(
            bos_token=bos_token,
            eos_token=eos_token,
            unk_token=unk_token,
            pad_token=None,
            add_prefix_space=False,
            add_prefix_new_line=False,
            lower_case=lower_case,
        )

        assert self._config.unk_token, "`unk_token` must be supplied for WordVocab."
        self._bos = [self._config.bos_token] if self._config.bos_token else []
        self._eos = [self._config.eos_token] if self._config.eos_token else []

        self.save_path = save_path
        self.vocab_size = vocab_size
        self.min_frequency = min_frequency
        self.delimiter = delimiter
        self.encode_special_tokens = encode_special_tokens
        self.decode_special_tokens = decode_special_tokens

    def _preprocess_text(self, text: str) -> str:
        """Pre-processes the text.

        Args:
            text: Input text.

        Returns:
            (str): Pre-processed text.

        """

        if self._config.add_prefix_space:
            text = " " + text
        if self._config.add_prefix_new_line:
            text = "\n" + text
        if self._config.lower_case:
            text = text.lower()

        return text

    def _add_file(self, path: str, verbose: Optional[bool] = True) -> None:
        """Setups the counter with tokens' frequencies for the entire file.

        Args:
            path: Input file.
            verbose: Whether should log additional verbosity.

        """

        if verbose:
            logger.debug(f"Counting file: {path}")

        assert os.path.exists(path), f"File does not exist: {path}"

        with open(path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                if verbose and idx > 0 and idx % 500000 == 0:
                    logger.debug(f"Completed line: {idx}")

                symbols = self._tokenize_text(line)
                self.counter.update(symbols)

    def _tokenize_text(self, text: str) -> List[str]:
        """Tokenizes the text.

        Args:
            text: Input text.

        Returns:
            (List[str]): Tokens.

        """

        text = self._preprocess_text(text)
        symbols = text.split(self.delimiter)

        return symbols

    def _clear(self) -> None:
        """Clears the vocabulary."""

        self.idx2sym = []
        self.sym2idx = OrderedDict()

    @overrides
    def load(self) -> None:
        """Loads a previously cached vocabulary file."""

        vocab_filepath = self._vocab_filepath()
        self._clear()

        with open(vocab_filepath, "r", encoding="utf-8") as f:
            for line in f:
                symb = line.strip().split()[0]
                self._add_symbol(symb)

        self.unk_idx = self.sym2idx[self._config.unk_token]

    def _vocab_filepath(self) -> str:
        """Gets the vocabulary file path.

        Returns:
            (str): Path to the vocabulary file.

        """

        vocab_dir = utils.full_path(os.path.join(self.save_path), create=True)

        return os.path.join(vocab_dir, "vocab.txt")

    def _save(self) -> None:
        """Saves the vocabulary."""

        vocab_filepath = self._vocab_filepath()
        with open(vocab_filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(self.idx2sym))

    @overrides
    def is_trained(self) -> bool:
        """Checks whether vocabulary has been trained.

        Returns:
            (bool): Whether vocabulary has been trained.

        """

        vocab_filepath = self._vocab_filepath()

        return os.path.exists(vocab_filepath)

    @overrides
    def train(self, filepaths: List[str]) -> None:
        """Trains tokenizer from a list of files.

        Args:
            filepaths: List of paths to input files.

        """

        logger.info(
            f"Training vocabulary with min_frequency = {self.min_frequency} and vocab_size = {self.vocab_size}, using {len(filepaths)} training file(s) at {self.save_path} ..."
        )

        assert len(filepaths)

        self._clear()

        for filepath in filepaths:
            self._add_file(filepath)

        # Adds specials tokens regardless of vocab_size
        for sym in self._config.get_special_tokens():
            self._add_special(sym)

        remaining_len = self.vocab_size - len(self) if self.vocab_size is not None else None
        for sym, cnt in self.counter.most_common(remaining_len):
            if cnt < self.min_frequency:
                break
            self._add_symbol(sym)

        with distributed_utils.sync_workers() as rank:
            if rank == 0:
                self._save()

        logger.info(f"Final vocabulary size = {len(self)} | Unique tokens = {len(self.counter)}")

    @overrides
    def encode_text(self, text: str) -> List[int]:
        """Encodes text into tokens.

        Args:
            text: Input text.

        Returns:
            (List[int]): Encoded text (tokens).

        """

        symbols = self._tokenize_text(text)

        if self.encode_special_tokens:
            symbols = self._bos + symbols + self._eos

        toks = self.tokens_to_ids(symbols)

        return toks

    @overrides
    def decode_text(self, ids: List[int]) -> str:
        """Decodes tokens into text.

        Args:
            ids: Tokens.

        Returns:
            (str): Decoded tokens (text).

        """

        syms = self.ids_to_tokens(ids)
        if self.decode_special_tokens and len(syms):
            if syms[0] == self._bos:
                syms = syms[1:]
            if len(syms) and syms[-1] == self._eos:
                syms = syms[:-1]

        return " ".join(syms)

    @overrides
    def special_token_id(self, sp: SpecialTokenEnum) -> int:
        """Gets the identifier of special token.

        Args:
            sp: Special token's enumerator.

        Returns:
            (int): Special token's identifier.

        """

        return self.token_to_id(self._config.special_token_name(sp))

    def _add_special(self, sym: str) -> None:
        """Adds a special symbol/token to vocabulary.

        Args:
            sym: Special symbol.

        """

        if sym not in self.sym2idx:
            self.idx2sym.append(sym)
            self.sym2idx[sym] = len(self.idx2sym) - 1
            setattr(self, "{}_idx".format(sym.strip("<>")), self.sym2idx[sym])

    def _add_symbol(self, sym: str) -> None:
        """Adds a symbol to vocabulary.

        Args:
            sym: Symbol.

        """

        if sym not in self.sym2idx:
            self.idx2sym.append(sym)
            self.sym2idx[sym] = len(self.idx2sym) - 1

    def _get_sym(self, idx: int) -> str:
        """Gets a symbol based on its index.

        Args:
            idx: Index of symbol.

        Returns:
            (str): Symbol.

        """

        assert 0 <= idx < len(self), f"Index {idx} out of range."

        return self.idx2sym[idx]

    def _get_idx(self, sym: str) -> int:
        """Gets an index based on its symbol.

        Args:
            idx: Symbol.

        Returns:
            (int): Index of symbol.

        """

        if sym in self.sym2idx:
            return self.sym2idx[sym]

        return self.sym2idx.get(sym, self.unk_idx)

    @overrides
    def token_to_id(self, t: str) -> int:
        """Converts a string-based token to its identifier.

        Args:
            t: String-based token.

        Returns:
            (int): Token's identifier.

        """

        return self._get_idx(t)

    @overrides
    def id_to_token(self, id: int) -> str:
        """Converts a token identifier to its string-based representation.

        Args:
            id: Token's identifier.

        Returns:
            (str): String-based token.

        """

        return self._get_sym(id)

    @overrides
    def tokens_to_ids(self, ts: List[str]) -> List[int]:
        """Converts a set of string-based tokens to their identifiers.

        Args:
            ts: String-based tokens.

        Returns:
            (List[int]): Tokens' identifiers.

        """

        return [self._get_idx(t) for t in ts]

    @overrides
    def ids_to_tokens(self, ids: List[int]) -> List[str]:
        """Converts a set of tokens' identifiers to their string-based representations.

        Args:
            ids: Tokens' identifiers.

        Returns:
            (List[str]): String-based tokens.

        """

        return [self._get_sym(id) for id in ids]

    @overrides
    def __len__(self) -> int:
        """Length of the vocabulary.

        Returns:
            (int): Length of the vocabulary.

        """

        return len(self.idx2sym)
