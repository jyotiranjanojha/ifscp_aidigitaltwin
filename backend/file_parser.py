import re
import pandas as pd
import io
import asyncio
from typing import Optional, Tuple
from fastapi import UploadFile, HTTPException
from pydantic import ValidationError

from models import ENTITY_SCHEMA_MAP, BYBaseModel

# Fixed regex: removed invalid double asterisks and fixed the double backslashes
FILENAME_PATTERN = re.compile(r"^if_snop_([a-z]+)-\d{14}\.csv$", re.IGNORECASE)

def parse_filename(filename: str) -> Optional[str]:
    # Removed redundant .lower() since re.IGNORECASE is used in the pattern
    match = FILENAME_PATTERN.match(filename.strip())
    if match:
        return match.group(1)
    return None

def get_schema_for_entity(entity: str) -> type[BYBaseModel]:
    schema = ENTITY_SCHEMA_MAP.get(entity.lower())
    if not schema:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Unknown entity type: {entity}",
                "supported_entities": sorted(ENTITY_SCHEMA_MAP.keys()),
            },
        )
    return schema

async def read_and_normalize_csv(file: UploadFile) -> pd.DataFrame:
    content = await file.read()
    header = content.splitlines()[0].decode("utf-8-sig", errors="ignore") if content else ""
    delimiter = max(["|", ",", "\t", ";"], key=header.count)
    df = pd.read_csv(io.BytesIO(content), sep=delimiter)
    df.columns = [col.strip().upper() for col in df.columns]
    return df

def validate_dataframe(df: pd.DataFrame, schema_class: type[BYBaseModel], entity: str) -> list[dict]:
    # Clean access to required columns
    required_columns = schema_class._required_columns
    missing = required_columns - set(df.columns)
    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Validation failed for {entity}",
                "missing_columns": sorted(list(missing)),
                "received_columns": sorted(list(df.columns)),
                "required_columns": sorted(list(required_columns)),
            },
        )
    
    records = df.to_dict(orient="records")
    
    # Catch validation errors to return clean HTTP 400 responses
    try:
        validated = [schema_class(**record).model_dump() for record in records]
    except ValidationError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Data validation failed for entity '{entity}'",
                "errors": e.errors()
            }
        )
    return validated

async def process_upload_file(file: UploadFile) -> Tuple[str, list[dict], dict]:
    entity = parse_filename(file.filename)
    if not entity:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Invalid filename format",
                "expected_pattern": "if_snop_<entity>-YYYYMMDDHHMMSS.csv",
                "received": file.filename,
                "supported_entities": sorted(ENTITY_SCHEMA_MAP.keys()),
            },
        )

    schema_class = get_schema_for_entity(entity)
    df = await read_and_normalize_csv(file)
    validated_records = validate_dataframe(df, schema_class, entity)

    return entity, validated_records, {"rows": len(validated_records), "columns": list(df.columns)}

async def process_multiple_files(files: list[UploadFile]) -> dict:
    results = {}
    
    # Process all files concurrently using asyncio.gather
    tasks = [process_upload_file(file) for file in files]
    processed_results = await asyncio.gather(*tasks)
    
    for entity, records, meta in processed_results:
        if entity in results:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate entity in upload: {entity}",
            )
        results[entity] = {"data": records, "meta": meta}
    return results
