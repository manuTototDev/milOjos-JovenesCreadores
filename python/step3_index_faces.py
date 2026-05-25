import os
import cv2
import numpy as np
import pickle
from insightface.app import FaceAnalysis
from tqdm import tqdm

def index_faces():
    # Base configuration
    current_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.join(current_dir, "..", "fcaesDes")
    db_file = os.path.join(current_dir, "face_database.pkl")
    
    # Initialize InsightFace
    # We use a standard provider (CPU for now as we don't know if user has GPU)
    app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=(640, 640))
    
    database = []
    
    # Process each year folder
    years = sorted([d for d in os.listdir(base_dir) if d.isdigit()])
    
    print(f"Starting Face Indexing using InsightFace...")
    
    for year in years:
        year_path = os.path.join(base_dir, year)
        crop_dir = os.path.join(year_path, "fotos_recortadas")
        
        if not os.path.exists(crop_dir):
            continue
            
        print(f"Indexing year: {year}")
        files = [f for f in os.listdir(crop_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        
        for filename in tqdm(files, desc=f"Year {year}"):
            img_path = os.path.join(crop_dir, filename)
            
            try:
                # Load image
                img = cv2.imread(img_path)
                if img is None:
                    continue
                
                # Get faces
                faces = app.get(img)
                
                if not faces:
                    # Optional: print(f"No face found in {filename}")
                    continue
                
                # Take the most prominent face
                # Each face has an 'embedding' (512-d for buffalo_l)
                # and a 'normed_embedding'
                face = faces[0]
                
                # Clean name: remove prefix 'foto_' if present
                clean_name = filename.replace('foto_', '')
                
                database.append({
                    'name': clean_name,
                    'year': year,
                    'embedding': face.normed_embedding,
                    'original_path': img_path
                })
                
            except Exception as e:
                print(f"Error processing {filename}: {e}")
                
    # Save database
    print(f"Saving {len(database)} entries to {db_file}...")
    with open(db_file, 'wb') as f:
        pickle.dump(database, f)
    
    print("Indexing complete!")

if __name__ == "__main__":
    index_faces()
