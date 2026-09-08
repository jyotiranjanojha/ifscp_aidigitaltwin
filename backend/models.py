from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import ClassVar, Optional
from datetime import date
import pandas as pd

from schema_config import REQUIRED_COLUMNS_BY_ENTITY


class BYBaseModel(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True, populate_by_name=True, extra="allow")

    @model_validator(mode="before")
    @classmethod
    def normalize_keys(cls, data: dict) -> dict:
        if isinstance(data, dict):
            normalized = {}
            for k, v in data.items():
                key = str(k).replace("\ufeff", "").replace("\xa0", "").strip().upper()
                if pd.isna(v):
                    normalized[key] = None
                else:
                    normalized[key] = v
            return normalized
        return data


class SourcingInput(BYBaseModel):
    ITEM: str
    SOURCE: str
    DEST: str
    SOURCING: Optional[str] = None
    TRANSMODE: Optional[str] = None
    EFF: Optional[str] = None
    DISC: Optional[str] = None
    PRIORITY: Optional[float] = None
    FACTOR: Optional[float] = None
    U_PLANMODULE: Optional[str] = None
    BASE_COST: Optional[float] = None
    MAX_CAPACITY: Optional[float] = None
    TRANSPORT_TIME: Optional[float] = None
    MIN_CAPACITY: Optional[float] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["sourcing"]


class SKUInput(BYBaseModel):
    ITEM: str
    LOC: str
    DEMAND: float
    PRIORITY: int = 1
    SAFETY_STOCK: Optional[float] = None
    MAX_INVENTORY: Optional[float] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["legacy_sku"]


class SnopSKUInput(BYBaseModel):
    ITEM: str
    LOC: str
    CUST: Optional[str] = None
    OHPOST: Optional[str] = None
    STORABLESW: Optional[int] = None
    INFINITESUPPLYSW: Optional[int] = None
    ENABLEOPT: Optional[int] = None
    U_ORDER_LEADTIME: Optional[float] = None
    SSRULE: Optional[float] = None
    U_ALLOCATION_HORIZON: Optional[int] = None
    U_RSP_HORIZON: Optional[int] = None
    U_PLANMODULE: Optional[str] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["sku"]


class LocationsInput(BYBaseModel):
    LOC: str
    DESCR: Optional[str] = None
    LOC_TYPE: Optional[str] = None
    U_SUPPLIER_CD: Optional[str] = None
    U_INT_EXT_SW: Optional[str] = None
    U_PLANMODULE: Optional[str] = None
    LOC_NAME: Optional[str] = None
    REGION: Optional[str] = None
    COUNTRY: Optional[str] = None
    LATITUDE: Optional[float] = None
    LONGITUDE: Optional[float] = None
    TIMEZONE: Optional[str] = None
    CALENDAR: Optional[str] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["locations"]


class ItemsInput(BYBaseModel):
    ITEM: str
    DESCR: Optional[str] = None
    ITEMCLASS: Optional[str] = None
    U_UOM: Optional[str] = None
    U_LONG_DESCR: Optional[str] = None
    U_STATUS: Optional[str] = None
    U_MAT_TYPE_CD: Optional[str] = None
    U_PROCESS_NM: Optional[str] = None
    U_PROCESSNODEUPPERCASE_TXT: Optional[str] = None
    U_PRODUCTNBR: Optional[str] = None
    U_CAPACITY_GROUP: Optional[str] = None
    U_CAPACITY_CORRIDOR: Optional[str] = None
    U_PS_DOT_PROCESS: Optional[str] = None
    U_MM_CODE_NAME: Optional[str] = None
    U_ITEM_LVL1: Optional[str] = None
    ITEMLOCOPPARAM: Optional[str] = None
    U_VERTICAL_SEGMENT: Optional[str] = None
    U_MARKET_CODE_NAME: Optional[str] = None
    U_MFG_PKG_TECHNOLOGY: Optional[str] = None
    U_DIE_CODE_NAME: Optional[str] = None
    U_PRIMARY_SI_CODE_NAME: Optional[str] = None
    U_PRODUCT_LINE: Optional[str] = None
    U_DLCP_PROCESS_CODE: Optional[str] = None
    U_INTERNAL_STEPPING: Optional[str] = None
    U_INTERNAL_REVISION: Optional[str] = None
    U_MFG_DEVICE_NAME: Optional[str] = None
    U_PERFORMANCE_GRADE_CODE: Optional[str] = None
    U_SPEC_SEQUENTIAL_NUMBER: Optional[str] = None
    U_MFG_STAGE: Optional[str] = None
    U_FUNCTIONAL_DESIGN_NAME: Optional[str] = None
    U_PLANMODULE: Optional[str] = None
    ITEM_NAME: Optional[str] = None
    ITEM_TYPE: Optional[str] = None
    CATEGORY: Optional[str] = None
    SUB_CATEGORY: Optional[str] = None
    UNIT_OF_MEASURE: Optional[str] = None
    WEIGHT: Optional[float] = None
    VOLUME: Optional[float] = None
    STANDARD_COST: Optional[float] = None
    LIST_PRICE: Optional[float] = None
    PLANNING_METHOD: Optional[str] = None
    LOT_SIZE: Optional[float] = None
    MIN_LOT_SIZE: Optional[float] = None
    MAX_LOT_SIZE: Optional[float] = None
    FIXED_LOT_SIZE: Optional[float] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["items"]


class NetworkInput(BYBaseModel):
    SOURCE: str
    DEST: str
    TRANSMODE: Optional[str] = None
    TRANSLEADTIME: Optional[float] = None
    LEADTIMEEFFCNYCAL: Optional[str] = None
    U_PLANMODULE: Optional[str] = None
    NETWORK_TYPE: Optional[str] = None
    PRIORITY: Optional[int] = None
    LEAD_TIME: Optional[float] = None
    TRANSPORT_MODE: Optional[str] = None
    DISTANCE: Optional[float] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["network"]


class CalendarsInput(BYBaseModel):
    CAL: str
    DESCR: Optional[str] = None
    PATTERNSW: Optional[float] = None
    TYPE: Optional[float] = None
    U_PLANMODULE: Optional[str] = None
    CALENDAR: Optional[str] = None
    CALENDAR_NAME: Optional[str] = None
    DESCRIPTION: Optional[str] = None
    BASE_CALENDAR: Optional[str] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["calendars"]


class CalPatternInput(BYBaseModel):
    CAL: str
    DESCR: Optional[str] = None
    PATTERN: str
    PATTERNSEQNUM: Optional[float] = None
    RANK: Optional[float] = None
    STARTDATE: Optional[str] = None
    ENDDATE: Optional[str] = None
    REPEATEVERYNDAYS: Optional[float] = None
    DAY: Optional[float] = None
    MONDAYSW: Optional[float] = None
    TUESDAYSW: Optional[float] = None
    WEDNESDAYSW: Optional[float] = None
    THURSDAYSW: Optional[float] = None
    FRIDAYSW: Optional[float] = None
    SATURDAYSW: Optional[float] = None
    SUNDAYSW: Optional[float] = None
    U_PLANMODULE: Optional[str] = None
    CALENDAR: Optional[str] = None
    DAY_OF_WEEK: Optional[int] = None
    DAY_OF_MONTH: Optional[int] = None
    WEEK_OF_MONTH: Optional[int] = None
    MONTH_OF_YEAR: Optional[int] = None
    IS_WORKING: bool = True
    SHIFT_HOURS: Optional[float] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["calpattern"]


class CalAttributeInput(BYBaseModel):
    CAL: str
    PATTERNSEQNUM: Optional[float] = None
    ATTRIBUTE: str
    VALUE: str
    STARTTIME: Optional[str] = None
    ENDTIME: Optional[str] = None
    U_PLANMODULE: Optional[str] = None
    UNNAMED_7: Optional[str] = Field(default=None, alias="UNNAMED: 7")
    UNNAMED_8: Optional[str] = Field(default=None, alias="UNNAMED: 8")
    UNNAMED_9: Optional[str] = Field(default=None, alias="UNNAMED: 9")
    UNNAMED_10: Optional[str] = Field(default=None, alias="UNNAMED: 10")
    CALENDAR: Optional[str] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["calattribute"]


class CustomerInput(BYBaseModel):
    CUST: str
    DESCR: Optional[str] = None
    U_HIERCOL1: Optional[str] = None
    U_HIERCOL2: Optional[str] = None
    U_HIERCOL3: Optional[str] = None
    U_CUST_TIER: Optional[str] = None
    U_DMDGROUP_LVL1: Optional[str] = None
    ENABLEOPT: Optional[float] = None
    CUSTOMER: Optional[str] = None
    CUSTOMER_NAME: Optional[str] = None
    CUSTOMER_TYPE: Optional[str] = None
    REGION: Optional[str] = None
    COUNTRY: Optional[str] = None
    CURRENCY: Optional[str] = None
    PAYMENT_TERMS: Optional[str] = None
    CREDIT_LIMIT: Optional[float] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["customer"]


class CustomerOrderInput(BYBaseModel):
    CUST: str
    EXTREF: Optional[str] = None
    ORDERID: str
    ITEM: str
    LOC: str
    QTY: float
    U_ORDER_TYPE: Optional[str] = None
    U_CREATION_DT: Optional[str] = None
    U_RGID_DT: Optional[str] = None
    U_CGID_DT: Optional[str] = None
    MAXLATEDUR: Optional[float] = None
    U_COMMITTED_CO_FLAG: Optional[str] = None
    U_ENGINEERING: Optional[float] = None
    U_SHUTTLE: Optional[float] = None
    U_SAMPLE: Optional[float] = None
    U_NPI: Optional[float] = None
    U_EXPEDITE: Optional[float] = None
    U_DPAS: Optional[float] = None
    U_SPECIAL: Optional[float] = None
    U_BACKLOG: Optional[float] = None
    LINEITEMEXTREF: Optional[str] = None
    FCSTSW: Optional[float] = None
    STATUS: Optional[float] = None
    OP_CONSUMEEARLY: Optional[float] = None
    U_PLANMODULE: Optional[str] = None
    DELRDD_CALC_DT: Optional[str] = None
    GI_DT: Optional[str] = None
    CUSTOMER: Optional[str] = None
    ORDER_ID: Optional[str] = None
    ORDER_DATE: Optional[date] = None
    REQUESTED_DATE: Optional[date] = None
    QUANTITY: Optional[float] = None
    UNIT_PRICE: Optional[float] = None
    PRIORITY: Optional[int] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["customerorder"]


class DfutoSKUFCSTInput(BYBaseModel):
    ITEM: str
    SKULOC: str
    DMDGROUP: Optional[str] = None
    STARTDATE: str
    TOTFCST: float
    TYPE: Optional[float] = None
    DUR: Optional[float] = None
    LOC: Optional[str] = None
    FCST_DATE: Optional[date] = None
    QUANTITY: Optional[float] = None
    FCST_TYPE: Optional[str] = None
    HORIZON: Optional[int] = None
    CONFIDENCE: Optional[float] = None
    SOURCE: Optional[str] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["dfutoskufcst"]


class InventoryInput(BYBaseModel):
    ITEM: str
    LOC: str
    QTY: Optional[float] = None
    AVAILDATE: Optional[str] = None
    U_PLANMODULE: Optional[str] = None
    ON_HAND: float = 0.0
    ON_ORDER: float = 0.0
    ALLOCATED: float = 0.0
    AVAILABLE: Optional[float] = None
    SAFETY_STOCK: Optional[float] = None
    MAX_INVENTORY: Optional[float] = None
    REORDER_POINT: Optional[float] = None
    ORDER_QTY: Optional[float] = None
    LAST_COUNT_DATE: Optional[date] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["inventory"]


class SKUEffInventoryParamInput(BYBaseModel):
    ITEM: str
    LOC: str
    EFF: Optional[str] = None
    MAXOHQTY: Optional[float] = None
    ENABLEOPT: Optional[float] = None
    MAXCOVDUR: Optional[float] = None
    MINSSQTY: Optional[float] = None
    SSCOVDUR: Optional[float] = None
    U_PLANMODULE: Optional[str] = None
    TARGET_SERVICE_LEVEL: Optional[float] = None
    SAFETY_STOCK_METHOD: Optional[str] = None
    SAFETY_STOCK_DAYS: Optional[float] = None
    MIN_DAYS_SUPPLY: Optional[float] = None
    MAX_DAYS_SUPPLY: Optional[float] = None
    REVIEW_PERIOD: Optional[int] = None
    LEAD_TIME_DEMAND_SD: Optional[float] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["skueffinventoryparam"]


class SchedRcptsInput(BYBaseModel):
    ITEM: str
    LOC: str
    SCHED_DATE: str
    START_DT: Optional[str] = None
    SEQNUM: Optional[float] = None
    PRODUCTION_METHOD: Optional[str] = None
    EXPLODESW: Optional[float] = None
    QTY: float
    QTYRECEIVED: Optional[float] = None
    U_PLANMODULE: Optional[str] = None
    RECEIPT_ID: Optional[str] = None
    DUE_DATE: Optional[date] = None
    QUANTITY: Optional[float] = None
    RECEIPT_TYPE: Optional[str] = None
    SOURCE: Optional[str] = None
    STATUS: Optional[str] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["schedrcpts"]


class SupersessionInput(BYBaseModel):
    ITEM: str
    LOC: str
    ALTITEM: str
    DMDGROUP: Optional[str] = None
    ALTITEMPRIORITY: Optional[float] = None
    DRAWQTY: Optional[float] = None
    ENABLEOPT: Optional[float] = None
    SUPERSEDED_ITEM: Optional[str] = None
    SUPERSESSION_TYPE: Optional[str] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None
    CONVERSION_FACTOR: Optional[float] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["supersession"]


class BillOfMaterialsInput(BYBaseModel):
    ITEM: str
    SUBORD: str
    LOC: str
    BOMNUM: Optional[float] = None
    OFFSET: Optional[float] = None
    EFF: Optional[str] = None
    DISC: Optional[str] = None
    DRAWQTY: float
    YIELDCAL: Optional[str] = None
    YIELDFACTOR: Optional[float] = None
    U_INTEL_BOMID: Optional[str] = None
    U_PLANMODULE: Optional[str] = None
    PARENT_ITEM: Optional[str] = None
    COMPONENT_ITEM: Optional[str] = None
    QUANTITY_PER: Optional[float] = None
    SCRAP_FACTOR: Optional[float] = None
    SUBSTITUTE_GROUP: Optional[str] = None
    OPTIONALITY: Optional[str] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["billofmaterials"]


class AltBillOfMaterialsInput(BYBaseModel):
    ITEM: str
    SUBORD: str
    LOC: str
    BOMNUM: Optional[float] = None
    ALTSUBORD: str
    ALTSUBORDDISC: Optional[str] = None
    ALTSUBORDEFF: Optional[str] = None
    OFFSET: Optional[float] = None
    EFF: Optional[str] = None
    DRAWQTY: float
    YIELDCAL: Optional[str] = None
    YIELDFACTOR: Optional[float] = None
    PRIORITY: Optional[float] = None
    U_INTEL_BOMID: Optional[str] = None
    U_PLANMODULE: Optional[str] = None
    PARENT_ITEM: Optional[str] = None
    ALT_BOM_ID: Optional[str] = None
    COMPONENT_ITEM: Optional[str] = None
    QUANTITY_PER: Optional[float] = None
    SCRAP_FACTOR: Optional[float] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["altbillofmaterials"]


class ProductionMethodInput(BYBaseModel):
    ITEM: str
    LOC: str
    PRODUCTIONMETHOD: str
    DESCR: Optional[str] = None
    BOMNUM: Optional[float] = None
    EFF: Optional[str] = None
    DISC: Optional[str] = None
    LEADTIME: Optional[float] = None
    LEADTIMEEFFCNYCAL: Optional[str] = None
    NONEWSUPPLYDATE: Optional[str] = None
    PRIORITY: Optional[float] = None
    INCQTY: Optional[float] = None
    SPLITFACTOR: Optional[float] = None
    U_PLANMODULE: Optional[str] = None
    METHOD: Optional[str] = None
    METHOD_NAME: Optional[str] = None
    DESCRIPTION: Optional[str] = None
    YIELD_FACTOR: Optional[float] = None
    SETUP_TIME: Optional[float] = None
    RUN_TIME: Optional[float] = None
    BATCH_SIZE: Optional[float] = None
    MIN_BATCH_SIZE: Optional[float] = None
    MAX_BATCH_SIZE: Optional[float] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["productionmethod"]


class ProductionStepInput(BYBaseModel):
    ITEM: str
    LOC: str
    PRODUCTIONMETHOD: str
    STEPNUM: float
    EFF: Optional[str] = None
    RES: Optional[str] = None
    PRODRATE: Optional[float] = None
    PRODRATECAL: Optional[str] = None
    PRODDUR: Optional[float] = None
    NEXTSTEPTIMING: Optional[float] = None
    U_PLANMODULE: Optional[str] = None
    METHOD: Optional[str] = None
    STEP: Optional[int] = None
    RESOURCE: Optional[str] = None
    SETUP_TIME: Optional[float] = None
    RUN_TIME: Optional[float] = None
    QUEUE_TIME: Optional[float] = None
    MOVE_TIME: Optional[float] = None
    YIELD_FACTOR: Optional[float] = None
    SCRAP_FACTOR: Optional[float] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["productionstep"]


class AltProductionStepInput(BYBaseModel):
    ITEM: str
    LOC: str
    PRODUCTIONMETHOD: str
    PRIMARYSTEPNUM: float
    EFF: Optional[str] = None
    ALTRES: str
    PRODRATE: Optional[float] = None
    PRODRATECAL: Optional[str] = None
    U_PLANMODULE: Optional[str] = None
    METHOD: Optional[str] = None
    ALT_STEP_ID: Optional[str] = None
    STEP: Optional[int] = None
    RESOURCE: Optional[str] = None
    PRIORITY: Optional[int] = None
    SETUP_TIME: Optional[float] = None
    RUN_TIME: Optional[float] = None
    YIELD_FACTOR: Optional[float] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["altproductionstep"]


class ResInput(BYBaseModel):
    RES: str
    DESCR: Optional[str] = None
    TYPE: Optional[float] = None
    CAL: Optional[str] = None
    CHECKMAXCAP: Optional[float] = None
    STAGE: Optional[str] = None
    RELEASEFENCEDUR: Optional[float] = None
    PEGGINGSW: Optional[float] = None
    U_RESTYPE: Optional[str] = None
    U_HIERCOL_1: Optional[str] = None
    U_HIERCOL_2: Optional[str] = None
    U_PLANMODULE: Optional[str] = None
    RESOURCE: Optional[str] = None
    RESOURCE_NAME: Optional[str] = None
    RESOURCE_TYPE: Optional[str] = None
    LOC: str
    CAPACITY: Optional[float] = None
    CAPACITY_UOM: Optional[str] = None
    SHIFT_PATTERN: Optional[str] = None
    CALENDAR: Optional[str] = None
    EFFICIENCY: Optional[float] = None
    UTILIZATION: Optional[float] = None
    COST_PER_HOUR: Optional[float] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["res"]


class PurchMethodInput(BYBaseModel):
    ITEM: str
    LOC: str
    PURCHMETHOD: str
    NONEWSUPPLYDATE: Optional[str] = None
    EFF: Optional[str] = None
    DISC: Optional[str] = None
    LEADTIME: Optional[float] = None
    U_PLANMODULE: Optional[str] = None
    METHOD: Optional[str] = None
    METHOD_NAME: Optional[str] = None
    SUPPLIER: Optional[str] = None
    SUPPLIER_SITE: Optional[str] = None
    LEAD_TIME: Optional[float] = None
    UNIT_COST: Optional[float] = None
    MIN_ORDER_QTY: Optional[float] = None
    MAX_ORDER_QTY: Optional[float] = None
    ORDER_MULTIPLE: Optional[float] = None
    FIXED_ORDER_COST: Optional[float] = None
    CARRYING_COST_PCT: Optional[float] = None
    EFFECTIVE_DATE: Optional[date] = None
    EXPIRY_DATE: Optional[date] = None

    _required_columns: ClassVar[set[str]] = REQUIRED_COLUMNS_BY_ENTITY["purchmethod"]


ENTITY_SCHEMA_MAP = {
    "sourcing": SourcingInput,
    "sku": SnopSKUInput,
    "locations": LocationsInput,
    "items": ItemsInput,
    "network": NetworkInput,
    "calendars": CalendarsInput,
    "calpattern": CalPatternInput,
    "calattribute": CalAttributeInput,
    "customer": CustomerInput,
    "customerorder": CustomerOrderInput,
    "dfutoskufcst": DfutoSKUFCSTInput,
    "inventory": InventoryInput,
    "skueffinventoryparam": SKUEffInventoryParamInput,
    "schedrcpts": SchedRcptsInput,
    "supersession": SupersessionInput,
    "billofmaterials": BillOfMaterialsInput,
    "altbillofmaterials": AltBillOfMaterialsInput,
    "productionmethod": ProductionMethodInput,
    "productionstep": ProductionStepInput,
    "altproductionstep": AltProductionStepInput,
    "res": ResInput,
    "purchmethod": PurchMethodInput,
}

__all__ = [
    "BYBaseModel",
    "SourcingInput",
    "SKUInput",
    "SnopSKUInput",
    "LocationsInput",
    "ItemsInput",
    "NetworkInput",
    "CalendarsInput",
    "CalPatternInput",
    "CalAttributeInput",
    "CustomerInput",
    "CustomerOrderInput",
    "DfutoSKUFCSTInput",
    "InventoryInput",
    "SKUEffInventoryParamInput",
    "SchedRcptsInput",
    "SupersessionInput",
    "BillOfMaterialsInput",
    "AltBillOfMaterialsInput",
    "ProductionMethodInput",
    "ProductionStepInput",
    "AltProductionStepInput",
    "ResInput",
    "PurchMethodInput",
    "ENTITY_SCHEMA_MAP",
]