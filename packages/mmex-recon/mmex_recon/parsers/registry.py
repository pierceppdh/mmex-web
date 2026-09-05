"""Registre des parseurs de relevés bancaires."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from mmex_recon.schemas import ParsedStatement
from mmex_recon.parsers.base import BaseParser
from mmex_recon.parsers.boursorama_cb import BoursoramaCbParser
from mmex_recon.parsers.boursorama_compte import BoursoramaCompteParser
from mmex_recon.parsers.postfinance import PostFinanceParser
from mmex_recon.parsers.swiss_visa import SwissVisaParser
from mmex_recon.parsers.yuh import YuhParser

logger = logging.getLogger(__name__)


class ParserRegistry:
    """Registre central des parseurs disponibles."""

    def __init__(self):
        self._parsers: list[BaseParser] = [
            SwissVisaParser(),
            BoursoramaCbParser(),
            BoursoramaCompteParser(),
            PostFinanceParser(),
            YuhParser(),
        ]
        self._parsers.sort(key=lambda p: p.priority, reverse=True)

    def detect_parser(self, pdf_path: Path) -> Optional[BaseParser]:
        """Détecte le parseur approprié pour un PDF."""
        text = ""
        try:
            parser_instance = self._parsers[0]
            text = parser_instance.extract_text(pdf_path)
        except Exception as exc:
            logger.error("Erreur lecture PDF %s: %s", pdf_path, exc)
            return None

        filename = pdf_path.name
        for parser in self._parsers:
            if parser.can_parse(text, filename):
                logger.info("Parseur détecté: %s pour %s", parser.parser_id, filename)
                return parser
        return None

    def parse(self, pdf_path: Path) -> ParsedStatement:
        """Parse un PDF avec le parseur détecté."""
        parser = self.detect_parser(pdf_path)
        if not parser:
            raise ValueError(f"Aucun parseur compatible pour {pdf_path.name}")
        return parser.parse(pdf_path)

    def list_parsers(self) -> list[str]:
        """Liste les IDs de parseurs enregistrés."""
        return [p.parser_id for p in self._parsers]


registry = ParserRegistry()