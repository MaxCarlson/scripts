from __future__ import annotations

import math
import re
from lxml import html

from . import utils
from .models import Scene
from .custom_session import CustomSession


class Movie:
    def __init__(self, url: str, session: CustomSession):
        self.input_url = url
        self.session = session
        self.url_content_type: str | None = None
        self.movie_id: str | None = None
        self.studio_name: str | None = None
        self.title: str | None = None
        self.total_duration_seconds: int | None = None
        self.performers: list | None = None
        self.scenes: list[Scene] = []
        self.cover_url_front: str | None = None
        self.cover_url_back: str | None = None
        self.scenes_boundaries = []
        self._scrape_info()

    def _scrape_info(self):
        """Scrape movie metadata from aebn.com"""
        response = self.session.get(self.input_url)
        response.raise_for_status()
        content = html.fromstring(response.content)
        self.url_content_type = self.input_url.split("/")[3]
        self.movie_id = self.input_url.split("/")[5]
        self.studio_name = self._extract_studio_name(content)
        self.title = content.xpath('//*[@class="dts-section-page-heading-title"]/h1/text()')[0].strip()
        total_duration_string = content.xpath('//*[@class="section-detail-list-item-duration"][2]/text()')[0].strip()
        self.total_duration_seconds = utils.duration_to_seconds(total_duration_string)
        self.studio_name = utils.remove_chars(self.studio_name)
        self.title = utils.remove_chars(self.title)
        self.performers = content.xpath('//section[@id="dtsPanelStarsDetailMovie"]//a/@title')
        scene_elements = content.xpath('//section[@id[starts-with(., "scene")]]')
        for scene_element in scene_elements:
            scene_performers = scene_element.xpath('.//li[@class="dts-scene-strip-stars"]//a/text()')
            raw_scene_id = scene_element.get("id", "")
            match = re.fullmatch(r"scene-(\d+)", raw_scene_id)
            scene = Scene(performers=scene_performers, scene_id=match.group(1) if match else None)
            self.scenes.append(scene)
        cover_front_sources = content.xpath('//*[@class="dts-movie-boxcover-front"]//img/@src')
        if cover_front_sources:
            self.cover_url_front = self._normalize_cover_url(cover_front_sources[0])

        cover_back_sources = content.xpath('//*[@class="dts-movie-boxcover-back"]//img/@src')
        if cover_back_sources:
            self.cover_url_back = self._normalize_cover_url(cover_back_sources[0])

    def _extract_studio_name(self, content) -> str:
        studio_names = content.xpath('//*[@class="dts-studio-name-wrapper"]/a/text()')
        if len(studio_names) > 0:
            return studio_names[0].replace(",", "").strip()
        return ""

    def calculate_scenes_boundaries(self, segment_duration: float):
        """Calculate scene segment boundaries with data from m.aebn.net"""
        response = self.session.get(f"https://m.aebn.net/movie/{self.movie_id}")
        response.raise_for_status()
        html_tree = html.fromstring(response.content)
        scene_elems = html_tree.xpath('//div[@class="scroller"]')
        if len(scene_elems) != len(self.scenes):
            raise ValueError(
                f"AEBN scene count mismatch: movie page has {len(self.scenes)} scenes "
                f"but timeline has {len(scene_elems)} entries"
            )
        for i, scene_el in enumerate(scene_elems):
            target_scene = self.scenes[i]
            target_scene.start_timing = int(scene_el.get("data-time-start"))
            target_scene.end_timing = target_scene.start_timing + int(scene_el.get("data-time-duration"))
            target_scene.start_segment = math.floor(int(target_scene.start_timing) / segment_duration)
            target_scene.end_segment = math.ceil(int(target_scene.end_timing) / segment_duration)

    def scene_ordinal_for_id(self, scene_id: str) -> int:
        """Resolve a numeric AEBN scene ID to its 1-based movie-page ordinal."""
        if not re.fullmatch(r"\d+", str(scene_id)):
            raise ValueError(f"Malformed AEBN scene ID: {scene_id!r}")

        seen: set[str] = set()
        for scene in self.scenes:
            if scene.scene_id is None:
                raise ValueError("Missing or malformed scene ID metadata in AEBN movie page")
            if not re.fullmatch(r"\d+", scene.scene_id):
                raise ValueError(f"Malformed AEBN scene ID metadata: {scene.scene_id!r}")
            if scene.scene_id in seen:
                raise ValueError(f"Duplicate AEBN scene ID metadata: {scene.scene_id}")
            seen.add(scene.scene_id)

        if not self.scenes:
            raise ValueError("Missing scene ID metadata in AEBN movie page")
        try:
            return next(index for index, scene in enumerate(self.scenes, start=1) if scene.scene_id == scene_id)
        except StopIteration as exc:
            raise ValueError(f"AEBN scene ID {scene_id} not found in movie") from exc

    @staticmethod
    def _normalize_cover_url(raw_url: str) -> str:
        clean_url = raw_url.strip().split("?")[0]
        if clean_url.startswith("//"):
            return f"https:{clean_url}"
        return clean_url
