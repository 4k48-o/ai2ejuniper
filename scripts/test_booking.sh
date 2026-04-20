#!/bin/bash
# Test booking flow with data isolation

BASE="http://localhost:8000/api/v1"
API_KEY="test-api-key-1"

case "${1:-}" in
  new-bob)
    echo "=== Create new conversation for Bob ==="
    curl -s -X POST "${BASE}/conversations" \
      -H "X-API-Key: ${API_KEY}" \
      -H "X-External-User-Id: bob" \
      -H "Content-Type: application/json" \
      -d '{"external_user_id": "bob"}' | python3 -m json.tool
    ;;
  new-alice)
    echo "=== Create new conversation for Alice ==="
    curl -s -X POST "${BASE}/conversations" \
      -H "X-API-Key: ${API_KEY}" \
      -H "X-External-User-Id: alice" \
      -H "Content-Type: application/json" \
      -d '{"external_user_id": "alice"}' | python3 -m json.tool
    ;;
  book)
    if [ -z "$2" ]; then echo "Usage: bash $0 book <conv_id>"; exit 1; fi
    echo "=== Bob books hotel (one-shot) ==="
    curl -N -s --max-time 120 -X POST "${BASE}/conversations/$2/messages/stream" \
      -H "X-API-Key: ${API_KEY}" \
      -H "X-External-User-Id: bob" \
      -H "Content-Type: application/json" \
      -d '{"content":"I want to book NH Collection Barcelona, check-in 2026-04-15, check-out 2026-04-18, guest Bob Smith, email bob@test.com. I confirm the booking, please proceed directly."}'
    echo ""
    ;;
  chat)
    if [ -z "$2" ] || [ -z "$3" ] || [ -z "$4" ]; then
      echo "Usage: bash $0 chat <conv_id> <user_id> <message>"
      exit 1
    fi
    curl -N -s --max-time 120 -X POST "${BASE}/conversations/$2/messages/stream" \
      -H "X-API-Key: ${API_KEY}" \
      -H "X-External-User-Id: $3" \
      -H "Content-Type: application/json" \
      -d "{\"content\":\"$4\"}"
    echo ""
    ;;
  bob)
    echo "=== Bob's bookings ==="
    curl -s "${BASE}/bookings" \
      -H "X-API-Key: ${API_KEY}" \
      -H "X-External-User-Id: bob" | python3 -m json.tool
    ;;
  alice)
    echo "=== Alice's bookings ==="
    curl -s "${BASE}/bookings" \
      -H "X-API-Key: ${API_KEY}" \
      -H "X-External-User-Id: alice" | python3 -m json.tool
    ;;
  *)
    echo "Usage:"
    echo "  bash $0 new-bob                        # Create Bob's conversation"
    echo "  bash $0 new-alice                      # Create Alice's conversation"
    echo "  bash $0 book <conv_id>                 # Bob books hotel in one shot"
    echo "  bash $0 chat <conv_id> <user> <msg>    # Send message as user"
    echo "  bash $0 bob                            # Check Bob's bookings"
    echo "  bash $0 alice                          # Check Alice's bookings (should be empty)"
    ;;
esac
