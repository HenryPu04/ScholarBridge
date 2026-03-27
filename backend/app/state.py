"""
Shared in-memory state for the JIT indexing pipeline.

Extracted here to avoid a circular import between:
  app/routers/summaries.py  (sets initial PENDING status)
  app/services/indexing_pipeline.py  (updates status through all stages)

Both modules import from this file. Neither imports from the other.
"""

from app.models.summary import PipelineStatus

# paper_id → current pipeline stage
pipeline_status: dict[str, PipelineStatus] = {}

# paper_id → human-readable status message (last error or progress note)
pipeline_messages: dict[str, str] = {}
