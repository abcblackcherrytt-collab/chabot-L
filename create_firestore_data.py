from google.cloud import firestore
from datetime import datetime, timezone
import sys

print("Creating Firestore data...")

try:
    # ADC（Application Default Credentials）を使用してFirestoreに接続
    db = firestore.Client(project='takahashi-451312', database='chabotline')
    print("Firestore client initialized successfully")
except Exception as e:
    print(f"Failed to initialize Firestore client: {e}")
    sys.exit(1)

now = datetime.now(timezone.utc).isoformat()

plans = [
    {
        "id": "free-perm-001",
        "plan": "free",
        "rag_corpus_id": "6942545116196241408",
        "model_name": "gemini-2.5-flash",
        "max_input_tokens": 8000,
        "max_output_tokens": 4000,
        "daily_message_limit": 3,
        "enabled": True,
        "created_at": now,
        "updated_at": now
    },
    {
        "id": "basic-perm-001",
        "plan": "basic",
        "rag_corpus_id": "1495705249682292736",
        "model_name": "gemini-2.5-flash",
        "max_input_tokens": 16000,
        "max_output_tokens": 8000,
        "daily_message_limit": 100,
        "enabled": True,
        "created_at": now,
        "updated_at": now
    },
    {
        "id": "pro-perm-001",
        "plan": "pro",
        "rag_corpus_id": "1495705249682292736",
        "model_name": "gemini-2.5-flash",
        "max_input_tokens": 32000,
        "max_output_tokens": 16000,
        "daily_message_limit": 500,
        "enabled": True,
        "created_at": now,
        "updated_at": now
    }
]

success_count = 0
for plan_data in plans:
    try:
        doc_ref = db.collection('rag_permissions').document(plan_data['id'])
        doc_ref.set(plan_data)
        print(f"✅ Success: {plan_data['plan']} plan created (ID: {plan_data['id']})")
        success_count += 1
    except Exception as e:
        print(f"❌ Error {plan_data['plan']}: {e}")

print(f"\n📊 Setup completed: {success_count}/{len(plans)} plans created successfully")
if success_count == len(plans):
    print("🎉 All Firestore data setup completed successfully!")
    sys.exit(0)
else:
    print("⚠️  Some plans failed to create. Please check the errors above.")
    sys.exit(1)
