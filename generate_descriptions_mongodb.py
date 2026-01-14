import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from openai import OpenAI
from pymongo import MongoClient


# MongoDB connection - loaded from .env
MONGO_URI = None
DB_NAME = None
COLLECTION_CATEGORIES = "course_categories"
COLLECTION_COURSES = "courses"

# Global MongoDB connection
client = None
db = None
collection_categories = None


def connect_mongodb():
    """Connect to MongoDB using credentials from .env"""
    global client, db, collection_categories, MONGO_URI, DB_NAME
    
    load_dotenv()
    
    MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://tp:03yrK0cnksd7xUWs@funding-stream.apgvlfi.mongodb.net/")
    DB_NAME = os.getenv("MONGO_DB_NAME", "tp-dev")
    COLLECTION_CATEGORIES = os.getenv("MONGO_COLLECTION", "course_categories")
    
    try:
        print(f"Connecting to MongoDB...")
        print(f"  Database: {DB_NAME}")
        print(f"  Collection: {COLLECTION_CATEGORIES}")
        
        # Add connection timeout and server selection timeout to handle DNS issues
        client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=30000,  # 30 seconds
            connectTimeoutMS=30000,
            socketTimeoutMS=30000
        )
        client.admin.command('ping')  # Test connection
        
        db = client[DB_NAME]
        collection_categories = db[COLLECTION_CATEGORIES]
        
        total_categories = collection_categories.count_documents({})
        print(f"  [OK] Connected! Found {total_categories} categories")
        
        return True
    except Exception as e:
        import traceback
        print(f"ERROR: Failed to connect to MongoDB: {e}", file=sys.stderr)
        traceback.print_exc()
        return False


def get_categories_batch(skip=0, batch_size=10, skip_existing=True):
    """
    Get a batch of categories directly from MongoDB and enrich with metadata from courses collection.
    Same logic as Excel version: match category_id from courses to _id from categories.
    """
    global collection_categories, db
    
    if collection_categories is None:
        return []
    
    collection_courses = db[COLLECTION_COURSES]
    
    # Build query - skip existing descriptions if requested
    query = {}
    if skip_existing:
        query = {
            "$or": [
                {"description": {"$exists": False}},
                {"description": None},
                {"description": ""},
                {"description": 0},  # MongoDB has 0 as placeholder - treat as no description
                {"description": {"$type": "null"}},
                {"description": {"$regex": "^\\s*$"}}  # Only whitespace
            ]
        }
    
    # Get batch directly from MongoDB
    cursor = collection_categories.find(query).skip(skip).limit(batch_size)
    
    categories_list = []
    for category_doc in cursor:
        category_id = category_doc.get("_id")
        category_title = category_doc.get("category_title")
        count = category_doc.get("count", 1)
        
        if not category_title:  # Skip empty categories
            continue
        
        # Find all courses that match this category using category_id (like Excel Sheet 2 matching Sheet 1 by _id)
        matching_courses = list(collection_courses.find({"category_id": category_id}).limit(100))
        
        if len(matching_courses) == 0:
            # No matching courses, use just the category title
            categories_list.append({
                'category_id': category_id,
                'category_title': category_title,
                'count': count if count else 1,
                'metadata': {}
            })
            continue
        
        # Aggregate metadata from all matching courses (like Excel Sheet 2 aggregation)
        levels = []
        awarding_orgs = []
        main_sectors = []
        sub_sectors = []
        course_types = []
        guided_hours = []
        total_times = []
        
        # Get awarding bodies collection for lookup
        collection_awarding_bodies = db['awarding_bodies']
        
        for course in matching_courses:
            # Extract metadata from course (same field names as Excel)
            if course.get('Level'):
                levels.append(course['Level'])
            
            # Get awarding body name from awarding_bodies collection using ab_id (ObjectId)
            if course.get('ab_id'):
                try:
                    from bson import ObjectId
                    # ab_id is already ObjectId, but ensure it's correct type
                    ab_id = course['ab_id']
                    if not isinstance(ab_id, ObjectId):
                        ab_id = ObjectId(ab_id)
                    ab_doc = collection_awarding_bodies.find_one({"_id": ab_id})
                    if ab_doc and ab_doc.get('AwardingOrgName'):
                        org_name = ab_doc['AwardingOrgName']
                        # Filter out placeholder/None values
                        if org_name and org_name.strip() and \
                           not org_name.upper().startswith('NONE') and \
                           'Generic award' not in org_name and \
                           org_name.strip() != '(blank)':
                            awarding_orgs.append(org_name)
                except Exception as e:
                    pass  # Skip if lookup fails
            
            if course.get('SectorSubjectArea1'):
                main_sectors.append(course['SectorSubjectArea1'])
            if course.get('SectorSubjectArea2'):
                sub_sectors.append(course['SectorSubjectArea2'])
            if course.get('LearnAimRefType'):
                course_types.append(course['LearnAimRefType'])
            if course.get('GuidedLearningHours'):
                try:
                    hours = float(course['GuidedLearningHours'])
                    if hours > 0:
                        guided_hours.append(hours)
                except:
                    pass
            if course.get('TotalQualificationTime'):
                try:
                    time_val = float(course['TotalQualificationTime'])
                    if time_val > 0:
                        total_times.append(time_val)
                except:
                    pass
        
        # Aggregate metadata (same as Excel version)
        metadata = {
            'levels': list(set(levels))[:10],  # Unique values, limit to 10
            'awarding_orgs': list(set(awarding_orgs))[:10],
            'main_sectors': list(set(main_sectors))[:10],
            'sub_sectors': list(set(sub_sectors))[:10],
            'course_types': list(set(course_types))[:10],
            'guided_hours': list(set(guided_hours))[:10],
            'total_times': list(set(total_times))[:10],
        }
        
        categories_list.append({
            'category_id': category_id,
            'category_title': category_title,
            'count': len(matching_courses) if matching_courses else count,
            'metadata': metadata
        })
    
    return categories_list


def load_system_prompt(path="system_prompt.json"):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg.get("prompt", "")


def validate_json(text):
    try:
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        parsed = json.loads(cleaned.strip())
        return True, "", parsed
    except json.JSONDecodeError as e:
        # Try to fix truncated JSON by extracting what we can
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        
        # Try to extract partial JSON objects
        try:
            # Find all complete JSON objects (ending with })
            import re
            # Match pattern: "key": { ... }
            pattern = r'"([^"]+)":\s*\{[^}]*"description":\s*"([^"]*(?:\\.[^"]*)*)"[^}]*"recognition":\s*\[([^\]]*)\][^}]*\}'
            matches = re.findall(pattern, cleaned, re.DOTALL)
            
            if matches:
                parsed = {}
                for i, (key, desc, rec) in enumerate(matches, 1):
                    # Clean up description
                    desc = desc.replace('\\"', '"').replace('\\n', ' ')
                    # Parse recognition array
                    try:
                        rec_list = json.loads(f'[{rec}]')
                    except:
                        rec_list = [r.strip().strip('"') for r in rec.split(',') if r.strip()]
                    parsed[f"Course {i}"] = {
                        "description": desc,
                        "recognition": rec_list[:3]  # Limit to 3 badges
                    }
                if parsed:
                    return True, "Extracted from truncated JSON", parsed
        except:
            pass
        
        return False, str(e), {}


def generate_batch_descriptions(system_prompt, batch_categories, batch_category_ids, batch_num, total_batches):
    client = OpenAI()
    
    user_prompt = "Generate descriptions for the following course categories:\n\n"
    for i, cat_info in enumerate(batch_categories, 1):
        user_prompt += f"{i}. {cat_info}\n"
    
    print(f"  Processing batch {batch_num}/{total_batches} ({len(batch_category_ids)} categories)...")
    start_time = time.time()
    
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=6000  # Increased further to prevent JSON truncation (10 categories need more space)
        )
        
        response_text = completion.choices[0].message.content.strip()
        is_valid, error_msg, descriptions = validate_json(response_text)
        
        if not is_valid:
            print(f"    ERROR: JSON parsing failed: {error_msg}", file=sys.stderr)
            print(f"    Response preview: {response_text[:200]}...", file=sys.stderr)
            return {cat_id: {"description": f"[ERROR: {error_msg}]", "recognition": []} for cat_id in batch_category_ids}
        
        elapsed_time = time.time() - start_time
        print(f"    [OK] Batch {batch_num} completed in {elapsed_time:.2f} seconds")
        
        output = {}
        desc_list = list(descriptions.values()) if descriptions else []
        
        for i, category_id in enumerate(batch_category_ids):
            # Try multiple key formats
            key_variants = [
                f"Course {i + 1}",
                f"{i + 1}",
                str(i + 1),
                i + 1
            ]
            
            found = False
            for key in key_variants:
                if key in descriptions:
                    desc_data = descriptions[key]
                    if isinstance(desc_data, dict):
                        output[category_id] = {
                            "description": desc_data.get("description", ""),
                            "recognition": desc_data.get("recognition", [])
                        }
                    else:
                        output[category_id] = {"description": str(desc_data), "recognition": []}
                    found = True
                    break
            
            # Fallback: Use position-based matching
            if not found and i < len(desc_list):
                desc_data = desc_list[i]
                if isinstance(desc_data, dict):
                    output[category_id] = {
                        "description": desc_data.get("description", ""),
                        "recognition": desc_data.get("recognition", [])
                    }
                    found = True
            
            if not found:
                output[category_id] = {"description": "[ERROR: Description not found]", "recognition": []}
        
        return output
        
    except Exception as e:
        print(f"    ERROR: Batch {batch_num} failed: {e}", file=sys.stderr)
        return {cat_id: {"description": f"[ERROR: {e}]", "recognition": []} for cat_id in batch_category_ids}


def generate_all_descriptions_direct():
    """
    Process categories directly from MongoDB in batches - no pre-loading!
    Query batch -> Process -> Save -> Next batch
    """
    global collection_categories
    
    system_prompt = load_system_prompt()
    
    # REGENERATE ALL - replace all existing descriptions
    # User said all descriptions are incorrect, so process everything
    query = {}  # No filter - process all categories
    total_to_process = collection_categories.count_documents(query)
    
    # Debug: Also check what descriptions actually exist
    total_all = collection_categories.count_documents({})
    with_desc = collection_categories.count_documents({
        "$and": [
            {"description": {"$exists": True}},
            {"description": {"$ne": None}},
            {"description": {"$ne": ""}},
            {"description": {"$ne": 0}},  # Exclude 0
            {"description": {"$not": {"$regex": "^\\s*$"}}}
        ]
    })
    print(f"  Total categories: {total_all}")
    print(f"  Categories with descriptions: {with_desc}")
    print(f"  Categories to process: {total_to_process}")
    
    if total_to_process == 0:
        print("All categories already have descriptions! Nothing to process.")
        return True
    
    batch_size = 10  # Categories per API call
    max_workers = int(os.getenv("MAX_WORKERS", "50"))
    total_batches = (total_to_process + batch_size - 1) // batch_size
    
    print(f"Processing {total_to_process} categories in batches of {batch_size}...")
    print(f"Using {max_workers} parallel workers\n")
    
    def process_and_save_batch(batch_num, skip_offset):
        """Process one batch and save to DB immediately"""
        # Get batch directly from DB - skip_existing=False to regenerate ALL
        categories_batch = get_categories_batch(skip=skip_offset, batch_size=batch_size, skip_existing=False)
        
        if not categories_batch:
            return 0  # No more categories
        
        # Build info strings for this batch - INCLUDE METADATA (awarding bodies, levels, etc.)
        categories_info = []
        category_ids = []
        
        for cat in categories_batch:
            category_id = cat['category_id']
            category_title = cat['category_title']
            count = cat.get('count', 1)
            metadata = cat.get('metadata', {})
            
            # Build rich info string with all metadata
            info_parts = [f"Category: {category_title}", f"Variants: {count}"]
            
            # Add awarding bodies (CRITICAL - must be included, but only real ones)
            awarding_orgs = metadata.get('awarding_orgs', [])
            # Filter out any remaining placeholder values
            real_awarding_orgs = [
                org for org in awarding_orgs 
                if org and org.strip() and 
                not org.upper().startswith('NONE') and 
                'Generic award' not in org and 
                org.strip() != '(blank)'
            ]
            if real_awarding_orgs:
                orgs_str = ", ".join(real_awarding_orgs[:3])  # Limit to 3 to avoid too long
                info_parts.append(f"Awarding Body: {orgs_str}")
            
            # Add levels
            levels = metadata.get('levels', [])
            if levels:
                levels_str = ", ".join(str(l) for l in levels[:3])
                info_parts.append(f"Level: {levels_str}")
            
            # Add sectors
            main_sectors = metadata.get('main_sectors', [])
            if main_sectors:
                sectors_str = ", ".join(main_sectors[:2])
                info_parts.append(f"Sector: {sectors_str}")
            
            # Add guided hours if available
            guided_hours = metadata.get('guided_hours', [])
            if guided_hours:
                avg_hours = sum(guided_hours) / len(guided_hours)
                info_parts.append(f"Guided Learning Hours: {int(avg_hours)}")
            
            info = " | ".join(info_parts)
            categories_info.append(info)
            category_ids.append(category_id)
        
        # Process this batch
        batch_output = generate_batch_descriptions(
            system_prompt,
            categories_info,
            category_ids,
            batch_num,
            total_batches
        )
        
        # Save immediately to MongoDB - ONLY update description, keep recognition badges unchanged
        success_count = 0
        for category_id, desc_data in batch_output.items():
            description = desc_data.get("description", "")
            
            if description and not description.startswith("[ERROR"):
                # ONLY update description field, leave recognition_detail_1, _2, _3 unchanged
                update_doc = {"description": description}
                
                try:
                    result = collection_categories.update_one(
                        {"_id": category_id},
                        {"$set": update_doc}
                    )
                    if result.modified_count > 0:
                        success_count += 1
                    else:
                        print(f"    WARNING: Category {category_id} not updated (matched: {result.matched_count})")
                except Exception as e:
                    print(f"    ERROR saving {category_id}: {e}")
        
        print(f"  [OK] Batch {batch_num}/{total_batches} processed and SAVED to DB ({success_count} categories)")
        return success_count
    
    # Process batches in parallel groups
    total_processed = 0
    
    for group_start in range(0, total_batches, max_workers):
        group_end = min(group_start + max_workers, total_batches)
        print(f"  Processing batches {group_start + 1}-{group_end} in parallel...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_batch = {}
            for batch_idx in range(group_start, group_end):
                batch_num = batch_idx + 1
                skip_offset = batch_idx * batch_size
                
                future = executor.submit(process_and_save_batch, batch_num, skip_offset)
                future_to_batch[future] = batch_num
            
            for future in as_completed(future_to_batch):
                batch_num = future_to_batch[future]
                try:
                    success_count = future.result()
                    total_processed += success_count
                except Exception as e:
                    print(f"    ERROR in batch {batch_num}: {e}")
        
        progress_pct = (total_processed / total_to_process) * 100 if total_to_process > 0 else 0
        print(f"  [OK] Completed batches {group_start + 1}-{group_end} ({total_processed}/{total_to_process} - {progress_pct:.1f}%)\n")
    
    print(f"\n[OK] Completed processing {total_processed} categories")
    return True


def main():
    load_dotenv()
    
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set. Put it in a .env file.", file=sys.stderr)
        return
    
    # Connect to MongoDB
    if not connect_mongodb():
        print("ERROR: Failed to connect to MongoDB.", file=sys.stderr)
        return
    
    print("\n*** Generating course descriptions only (recognition badges preserved) ***")
    print("Processing directly from MongoDB - no pre-loading!\n")
    
    # Process directly from MongoDB in batches
    generate_all_descriptions_direct()
    
    # Close MongoDB connection
    if client:
        client.close()
        print("\n[OK] MongoDB connection closed")


if __name__ == "__main__":
    main()
