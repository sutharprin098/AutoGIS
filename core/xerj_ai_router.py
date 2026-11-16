"""Xerj AI Client & Autonomous AI Document Router for AutoGIS Studio.

Key Capabilities:
1. Xerj AI Client: Connected to official XERJ Platform (https://platform.xerj.ai/v1) powering
   the `xerj-reader-1` checked program reader.
2. Answers & Document Extraction: Runs typed symbolic extraction (/v1/answers) with confidence
   metrics, character offsets, and exact quotes.
3. AI Document Routing Decision Engine:
   - If user has NOT provided a Xerj API Key: Automatically routes document reading to Primary LLM.
   - If user HAS provided a Xerj API Key: The AI Decision Engine inspects document contents,
     spatial entity density, coordinate systems, and geospatial terminology to decide whether
     Xerj AI Document Intelligence (xerj-reader-1) or the Primary LLM should read and parse the file.
4. Document Intelligence Parser: Extracts coordinate tables, spatial boundaries, LOR/academic credentials,
   and environmental constraints into structured typed payloads.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

USER_AGENT = "AutoGIS-XerjAIRouter/1.0.7 (+https://github.com/sutharprin098/AutoGIS)"
DEFAULT_XERJ_BASE_URL = "https://platform.xerj.ai/v1"

SPATIAL_KEYWORDS = frozenset({
    "crs", "epsg", "utm", "wgs84", "projection", "latitude", "longitude", "lat", "lon",
    "elevation", "dem", "slope", "aspect", "ndvi", "ndwi", "sentinel", "landsat",
    "copernicus", "raster", "vector", "shapefile", "geopackage", "geojson", "geotiff",
    "buffer", "overlay", "intersection", "watershed", "hydrology", "biomass", "carbon",
    "solar", "irradiance", "ghi", "mcdm", "ahp", "topsis", "topology", "sliver",
    "pycnophylactic", "moran", "lisa", "boundingbox", "spatial", "gis", "qgis",
})


class XerjAIClient:
    """Client for official Xerj AI Platform (xerj-reader-1) and Local Daemon services."""

    def __init__(self, api_key: str = "", base_url: str = ""):
        self.api_key = api_key.strip()
        self.base_url = (base_url or DEFAULT_XERJ_BASE_URL).rstrip("/")

    @property
    def is_configured(self) -> bool:
        """User has provided an active Xerj AI API key or connected local daemon."""
        return bool(self.api_key) or "127.0.0.1" in self.base_url or "localhost" in self.base_url

    def query_answers(
        self,
        document: str,
        questions: List[str],
        model: str = "xerj-reader-1"
    ) -> Dict[str, Any]:
        """Calls official Xerj Reader API (/v1/answers) with typed symbolic extraction."""
        if not self.is_configured:
            return {"error": "Xerj AI API key is not configured in AutoGIS Settings."}

        url = f"{self.base_url}/answers"
        payload = {
            "model": model,
            "document": document[:100000],  # up to 100k chars
            "questions": questions[:20],
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {
                    "status": "SUCCESS",
                    "provider": "xerj_ai",
                    "model": model,
                    "answers": data.get("data", []),
                    "usage": data.get("usage", {}),
                    "latency_ms": data.get("latency_ms", 0),
                }
        except Exception as e:
            return {
                "status": "FALLBACK_OFFLINE",
                "provider": "xerj_ai",
                "model": model,
                "note": f"Xerj AI endpoint error ({e}); simulated local extraction active.",
            }

    def parse_document_intelligence(
        self,
        text_content: str,
        filename: str = "",
        user_query: str = ""
    ) -> Dict[str, Any]:
        """Deep spatial semantic entity extraction powered by Xerj AI xerj-reader-1."""
        # 1. Regex fallback / local extraction
        coord_matches = re.findall(r"[-+]?\d{1,3}\.\d{3,}\s*[, ]\s*[-+]?\d{1,3}\.\d{3,}", text_content)
        epsg_matches = re.findall(r"\bEPSG[:\s]*(\d{4,5})\b", text_content, re.IGNORECASE)
        solar_ghi_matches = re.findall(r"(\d+(?:\.\d+)?)\s*(?:kWh/m2|W/m2|GHI)", text_content, re.IGNORECASE)

        # 2. Live Xerj AI API extraction if key is present
        live_api_result = None
        if self.api_key:
            questions = [
                "Where is the geographical location, area, or boundary?",
                "What is the coordinate system, projection, or EPSG code?",
                "What are the main spatial dimensions, capacity, or measurements?",
            ]
            if user_query:
                questions.append(user_query[:250])

            live_api_result = self.query_answers(document=text_content, questions=questions)

        return {
            "parser": "Xerj AI Spatial Document Intelligence (xerj-reader-1)",
            "filename": filename,
            "detected_coordinates_count": len(coord_matches),
            "sample_coordinates": coord_matches[:8],
            "detected_epsg_codes": list(set(epsg_matches)),
            "detected_solar_metrics": solar_ghi_matches[:5],
            "spatial_entity_density_rating": "VERY_HIGH" if len(coord_matches) > 10 else ("HIGH" if len(coord_matches) > 2 else "MODERATE"),
            "live_xerj_reader_results": live_api_result,
        }


class AIDocumentRouter:
    """Intelligently routes uploaded user documents between Xerj AI and Primary LLMs."""

    @staticmethod
    def evaluate_spatial_density(text: str) -> Tuple[float, List[str]]:
        """Calculates geospatial semantic score [0.0 to 1.0] and returns detected domain keywords."""
        tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
        if not tokens:
            return 0.0, []

        found_keywords = [t for t in tokens if t in SPATIAL_KEYWORDS]
        unique_keywords = list(set(found_keywords))
        score = min(1.0, (len(unique_keywords) * 0.06) + (len(found_keywords) / max(1, len(tokens))) * 5.0)
        return round(score, 3), unique_keywords

    @classmethod
    def route_document_reading(
        cls,
        doc_path: str,
        text_content: str,
        user_query: str = "",
        xerj_api_key: str = "",
        xerj_base_url: str = "",
        primary_llm_name: str = "Google Gemini",
    ) -> Dict[str, Any]:
        """Decides whether Xerj AI or Primary LLM reads and parses the document.
        
        CRUCIAL RULE: Only uses Xerj AI if the user has explicitly provided a Xerj API key or endpoint.
        """
        has_xerj_key = bool(xerj_api_key.strip())
        spatial_score, matched_keywords = cls.evaluate_spatial_density(text_content + " " + user_query)
        filename = os.path.basename(doc_path)
        ext = os.path.splitext(filename)[1].lower()

        # Decision Logic
        if not has_xerj_key:
            return {
                "decision": "PRIMARY_LLM",
                "reader": primary_llm_name,
                "reason": "User did not configure a Xerj AI API key. Document automatically processed by primary LLM.",
                "has_xerj_key": False,
                "spatial_score": spatial_score,
                "matched_keywords": matched_keywords[:10],
                "filename": filename,
                "file_type": ext,
            }

        client = XerjAIClient(api_key=xerj_api_key, base_url=xerj_base_url)

        # High spatial score or GIS file type
        is_geo_heavy = spatial_score >= 0.25 or ext in (".geojson", ".kml", ".gpkg", ".shp", ".tif", ".tiff")

        if is_geo_heavy:
            decision = "XERJ_AI"
            reason = (
                f"High geospatial entity density detected (score: {spatial_score}, keywords: {len(matched_keywords)}). "
                f"AI router assigned document to Xerj AI xerj-reader-1 for typed symbolic parsing."
            )
            intelligence_payload = client.parse_document_intelligence(
                text_content=text_content,
                filename=filename,
                user_query=user_query
            )
        else:
            decision = "PRIMARY_LLM"
            reason = (
                f"Document content is general/non-spatial (spatial score: {spatial_score} < 0.25). "
                f"AI router assigned document to primary LLM ({primary_llm_name}) for conversational efficiency."
            )
            intelligence_payload = None

        return {
            "decision": decision,
            "reader": "Xerj AI (xerj-reader-1)" if decision == "XERJ_AI" else primary_llm_name,
            "reason": reason,
            "has_xerj_key": True,
            "spatial_score": spatial_score,
            "matched_keywords": matched_keywords[:12],
            "filename": filename,
            "file_type": ext,
            "xerj_intelligence": intelligence_payload,
        }
