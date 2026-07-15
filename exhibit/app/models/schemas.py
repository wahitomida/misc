# -*- coding: utf-8 -*-
"""Pydantic スキーマ定義"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class ExhibitionInfo(BaseModel):
    name: str = ""
    url: str = ""
    exhibitor_list_url: str = ""
    venue: str = ""
    dates: str = ""
    organizer: str = ""


class ExhibitionFetchRequest(BaseModel):
    url: str = ""
    name: str = ""


class CompanyInput(BaseModel):
    name: str
    memo: str = ""


class ResearchRequest(BaseModel):
    exhibition: ExhibitionInfo
    purpose: str
    themes: list[str]
    companies: list[CompanyInput]


class RecommendRequest(BaseModel):
    exhibition: ExhibitionInfo
    purpose: str
    themes: list[str]


class RegenerateRequest(BaseModel):
    exhibition: ExhibitionInfo
    purpose: str
    themes: list[str]
    company: CompanyInput
    sections: list[str] = []
    additional_instruction: str = ""


class AnalysisExecuteRequest(BaseModel):
    report_data: dict
    analyses: list[int]


class ConfigSaveRequest(BaseModel):
    user_id: str = "default"
    themes: list[str] = []
    purpose: str = ""
    dark_mode: bool = False


class ExportMarkdownRequest(BaseModel):
    exhibition: ExhibitionInfo
    purpose: str
    themes: list[str]
    results: list[dict]


class ExportTextRequest(BaseModel):
    exhibition: ExhibitionInfo
    companies: list[CompanyInput]
    purpose: str
    themes: list[str]


class ProductInfo(BaseModel):
    name: str = ""
    description: str = ""
    category: str = ""


class BasicInfo(BaseModel):
    official_name: Optional[str] = None
    headquarters: Optional[str] = None
    founded: Optional[str] = None
    employees: Optional[str] = None
    revenue: Optional[str] = None
    url: Optional[str] = None


class BusinessInfo(BaseModel):
    industry: Optional[str] = None
    main_products: list[ProductInfo] = []


class TechnologyInfo(BaseModel):
    core_tech: list[str] = []
    tech_stack: Optional[str] = None
    api_sdk: Optional[str] = None
    open_source: Optional[str] = None
    patents: Optional[str] = None


class ExhibitionContent(BaseModel):
    content: str = ""
    confidence: str = "estimated"
    source: Optional[str] = None


class ExhibitionStatus(BaseModel):
    status: str = "unknown"
    evidence_url: Optional[str] = None
    contents: list[ExhibitionContent] = []


class MarketInfo(BaseModel):
    competitors: list[str] = []
    market_share: Optional[str] = None
    target: Optional[str] = None
    case_studies: Optional[str] = None


class CollaborationInfo(BaseModel):
    api_level: Optional[str] = None
    trial: Optional[str] = None
    partner_program: Optional[str] = None
    pricing: Optional[str] = None


class CompanyResult(BaseModel):
    company_name: str
    basic_info: BasicInfo = BasicInfo()
    business: BusinessInfo = BusinessInfo()
    technology: TechnologyInfo = TechnologyInfo()
    exhibition: ExhibitionStatus = ExhibitionStatus()
    market: MarketInfo = MarketInfo()
    collaboration: CollaborationInfo = CollaborationInfo()
    relevance_score: int = 1
    relevance_themes: list[str] = []
    sources: list[dict] = []
    search_queries: list[str] = []
    status: str = "completed"
    error: Optional[str] = None
