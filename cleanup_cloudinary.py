import os
import sys
import cloudinary
import cloudinary.api
import cloudinary.uploader
from dotenv import load_dotenv

def main():
    print("========================================")
    print("🔥 HotShort Cloudinary Cleanup Utility 🔥")
    print("========================================")

    # Load environment variables
    env_files = [".env", ".env.local", ".env.worker"]
    for ef in env_files:
        if os.path.exists(ef):
            load_dotenv(ef, override=True)

    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")

    if not all([cloud_name, api_key, api_secret]):
        print("❌ ERROR: Cloudinary credentials not found in environment variables.")
        print("Please ensure CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET are set in .env.local or .env.worker")
        sys.exit(1)

    print(f"✅ Connected to Cloudinary (Cloud Name: {cloud_name})")
    
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True
    )

    print("\n⚠️ WARNING: This will delete ALL videos and images in your Cloudinary account.")
    print("⚠️ Use this only when you are hitting the 10GB free tier limit.")
    
    confirm = input("\nType 'DELETE' to confirm: ")
    if confirm != 'DELETE':
        print("Aborted.")
        sys.exit(0)

    print("\nFetching resources...")
    deleted_count = 0
    
    try:
        # Delete Videos
        print("Deleting videos...")
        next_cursor = None
        while True:
            response = cloudinary.api.resources(resource_type="video", max_results=100, next_cursor=next_cursor)
            resources = response.get("resources", [])
            if not resources:
                break
                
            public_ids = [r["public_id"] for r in resources]
            print(f"Deleting batch of {len(public_ids)} videos...")
            cloudinary.api.delete_resources(public_ids, resource_type="video")
            deleted_count += len(public_ids)
            
            next_cursor = response.get("next_cursor")
            if not next_cursor:
                break

        # Delete Images
        print("Deleting images...")
        next_cursor = None
        while True:
            response = cloudinary.api.resources(resource_type="image", max_results=100, next_cursor=next_cursor)
            resources = response.get("resources", [])
            if not resources:
                break
                
            public_ids = [r["public_id"] for r in resources]
            print(f"Deleting batch of {len(public_ids)} images...")
            cloudinary.api.delete_resources(public_ids, resource_type="image")
            deleted_count += len(public_ids)
            
            next_cursor = response.get("next_cursor")
            if not next_cursor:
                break
                
        print(f"\n✅ Successfully deleted {deleted_count} files from Cloudinary!")
        print("Your 10GB storage limit should be cleared now.")
        
    except Exception as e:
        print(f"\n❌ Error during deletion: {e}")
        print("Make sure your API Key has 'Admin API' permissions in Cloudinary.")

if __name__ == "__main__":
    main()
