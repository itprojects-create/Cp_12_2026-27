"""Announcement intelligence package (migration §24, §8 item 2).

Raw NSE/BSE announcement -> timestamp validation -> deterministic
normalization -> (optional) LLM structured extraction -> schema validation ->
deterministic event rule -> blackout / risk action.

The LLM NEVER outputs orders: extraction is schema-validated to Announcement,
and any payload carrying trade directives is rejected before it can reach the
blackout engine. The deterministic engine alone decides consequences.
"""
