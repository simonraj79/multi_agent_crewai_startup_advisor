# OpenRouter figures

Generated 2026-09-05T16:37:31Z.

**No generation ids were supplied.** That is the expected answer for
a SYNTHETIC run: `service/runner.py` writes `response_id: None` on
the LLM after-frame, because a double has no honest provider id to
invent. A PAID run whose ids are all absent is a defect - the id is
on `LLMCallCompletedEvent` and `events/serializer.py:525` records it.
