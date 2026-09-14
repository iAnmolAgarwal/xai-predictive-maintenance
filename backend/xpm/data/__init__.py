"""Dataset acquisition and normalisation for both plants.

Public surface: the typed loaders in :mod:`xpm.data.loader` and the channel /
schema definitions in :mod:`xpm.data.schema`. Downstream modules never touch a
raw dataset path.
"""

from xpm.data.loader import (
    Manifest,
    list_machines,
    load_ai4i,
    load_ims,
    load_manifest,
    load_plant,
    manifest_path,
    processed_parquet,
)
from xpm.data.schema import (
    AI4I_CHANNELS,
    IMS_BANDS_HZ,
    IMS_CHANNELS,
    PlantId,
    SchemaError,
    channels_for,
    schema_for,
    units_for,
    validate,
)

__all__ = [
    "AI4I_CHANNELS",
    "IMS_BANDS_HZ",
    "IMS_CHANNELS",
    "Manifest",
    "PlantId",
    "SchemaError",
    "channels_for",
    "list_machines",
    "load_ai4i",
    "load_ims",
    "load_manifest",
    "load_plant",
    "manifest_path",
    "processed_parquet",
    "schema_for",
    "units_for",
    "validate",
]
