# Scalper A2A webhook protocol

Scalper emits paper-only diagnostic, research, capability, and tool-review
events to a configured relay. The relay never executes trades or tools.

## Configuration

```env
A2A_RELAY_URL=https://relay.example/api/a2a/messages
A2A_SHARED_SECRET=replace-with-a-long-random-secret
```

When either value is absent, events remain in the local `a2a_messages` outbox
with status `queued`. Delivery uses `POST` JSON and the `X-A2A-Signature`
header (`sha256=` HMAC-SHA256 over the exact request body).

## Endpoints

- `GET /.well-known/a2a-agent-card.json` — agent capabilities and webhook URL
- `POST /api/a2a/messages` — receive a signed inbound event
- `POST /api/a2a/messages/{message_id}/ack` — acknowledge an event
- `POST /api/a2a/messages/{message_id}/respond` — attach a Codex response
- `GET /api/a2a/messages` — inspect the outbox/inbox
- `POST /api/a2a/emit` — create an outbound event for diagnostics/testing

Every message includes `protocol`, `version`, `message_id`, `correlation_id`,
`from`, `to`, `type`, `requires_user_approval`, `paper_only`, and `payload`.
Inbound research is treated as untrusted evidence. It is evaluated by the
server LLM and cannot directly mutate strategy settings or execute real orders.

## LLM_PAPER position ownership

For `LLM_PAPER`, the LLM may use the position tools to HOLD, update symbol-
specific stop-loss/take-profit/max-hold values, or close the paper position.
The configured LLM plan is enforced by the analyzer. Legacy fixed early-failure,
trailing, time-decay, and legacy max-hold exits are not applied to these
positions. All decisions are recorded in `decision_logs` and plan changes in
`signals` as `LLM_PLAN_UPDATED`.
