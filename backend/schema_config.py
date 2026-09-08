"""Central schema configuration for Blue Yonder entity validation.

Update this file when native BY exports add, rename, or promote columns to
required keys. The Pydantic models and real-data audit both reference these
maps so schema drift is handled in one place.
"""

REQUIRED_COLUMNS_BY_ENTITY: dict[str, set[str]] = {
    "sourcing": {"ITEM", "SOURCE", "DEST"},
    "legacy_sku": {"ITEM", "LOC", "DEMAND"},
    "sku": {"ITEM", "LOC"},
    "locations": {"LOC"},
    "items": {"ITEM"},
    "network": {"SOURCE", "DEST"},
    "calendars": {"CAL"},
    "calpattern": {"CAL", "PATTERN"},
    "calattribute": {"CAL", "ATTRIBUTE", "VALUE"},
    "customer": {"CUST"},
    "customerorder": {"CUST", "ORDERID", "ITEM", "LOC", "QTY"},
    "dfutoskufcst": {"ITEM", "SKULOC", "STARTDATE", "TOTFCST"},
    "inventory": {"ITEM", "LOC"},
    "skueffinventoryparam": {"ITEM", "LOC"},
    "schedrcpts": {"ITEM", "LOC", "SCHED_DATE", "QTY"},
    "supersession": {"ITEM", "LOC", "ALTITEM"},
    "billofmaterials": {"ITEM", "SUBORD", "LOC", "DRAWQTY"},
    "altbillofmaterials": {"ITEM", "SUBORD", "LOC", "ALTSUBORD", "DRAWQTY"},
    "productionmethod": {"ITEM", "LOC", "PRODUCTIONMETHOD"},
    "productionstep": {"ITEM", "LOC", "PRODUCTIONMETHOD", "STEPNUM"},
    "altproductionstep": {"ITEM", "LOC", "PRODUCTIONMETHOD", "PRIMARYSTEPNUM", "ALTRES"},
    "res": {"RES", "LOC"},
    "purchmethod": {"ITEM", "LOC", "PURCHMETHOD"},
}

PRIMARY_KEY_COLUMNS_BY_ENTITY: dict[str, set[str]] = {
    "sourcing": {"ITEM", "SOURCE", "DEST"},
    "sku": {"ITEM", "LOC"},
    "locations": {"LOC"},
    "items": {"ITEM"},
    "network": {"SOURCE", "DEST"},
    "calendars": {"CAL"},
    "calpattern": {"CAL", "PATTERN"},
    "calattribute": {"CAL", "ATTRIBUTE"},
    "customer": {"CUST"},
    "customerorder": {"CUST", "ORDERID", "ITEM", "LOC"},
    "dfutoskufcst": {"ITEM", "SKULOC", "STARTDATE"},
    "inventory": {"ITEM", "LOC"},
    "skueffinventoryparam": {"ITEM", "LOC"},
    "schedrcpts": {"ITEM", "LOC", "SCHED_DATE"},
    "supersession": {"ITEM", "LOC", "ALTITEM"},
    "billofmaterials": {"ITEM", "SUBORD", "LOC"},
    "altbillofmaterials": {"ITEM", "SUBORD", "LOC", "ALTSUBORD"},
    "productionmethod": {"ITEM", "LOC", "PRODUCTIONMETHOD"},
    "productionstep": {"ITEM", "LOC", "PRODUCTIONMETHOD", "STEPNUM"},
    "altproductionstep": {"ITEM", "LOC", "PRODUCTIONMETHOD", "PRIMARYSTEPNUM", "ALTRES"},
    "res": {"RES", "LOC"},
    "purchmethod": {"ITEM", "LOC", "PURCHMETHOD"},
}
