import os
import cv2
import numpy as np
import pickle
from insightface.app import FaceAnalysis
from collections import Counter

def webcam_search():
    # Base configuration
    current_dir = os.path.dirname(os.path.abspath(__file__))
    db_file = os.path.join(current_dir, "face_database.pkl")
    
    if not os.path.exists(db_file):
        print(f"Error: Database not found at {db_file}. Please run step3_index_faces.py first.")
        return

    print("Loading face database...")
    with open(db_file, 'rb') as f:
        database = pickle.load(f)
    print(f"Loaded {len(database)} indexed faces.")

    # Initialize InsightFace
    app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=(640, 640))
    
    # Open Webcam
    cap = cv2.VideoCapture(0)
    
    if not cap.isOpened():
        print("Error: Could not open webcam.")
        return

    print("Live Search Started. Press 'q' to quit.")
    
    # Pre-compute all embeddings into a matrix for speed
    db_embeddings = np.array([entry['embedding'] for entry in database])
    
    # Stabilization and State
    history = []
    MAX_HISTORY = 15
    current_display_indices = None # Store what we are currently showing
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        frame = cv2.flip(frame, 1)
        faces = app.get(frame)
        
        if faces:
            faces = sorted(faces, key=lambda x: (x.bbox[2]-x.bbox[0])*(x.bbox[3]-x.bbox[1]), reverse=True)
            main_face = faces[0]
            
            bbox = main_face.bbox.astype(int)
            cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)
            
            # Search
            target_embedding = main_face.normed_embedding
            similarities = np.dot(db_embeddings, target_embedding)
            
            # Get current top match info
            best_idx = np.argmax(similarities)
            
            # Stabilization: Add to history
            history.append(best_idx)
            if len(history) > MAX_HISTORY:
                history.pop(0)
            
            # Determine "Stable Best Match"
            most_common_id, count = Counter(history).most_common(1)[0]
            
            # Lógica "Sticky": Solo actualizamos el panel si:
            # 1. No hay nada mostrándose.
            # 2. El match más común ha cambiado Y es muy estable (ej. 8 de 15 frames).
            if current_display_indices is None or (most_common_id != current_display_indices[0] and count >= 8):
                current_display_indices = np.argsort(similarities)[-4:][::-1]
                
                # Create composite panel
                canvas = np.zeros((850, 600, 3), dtype=np.uint8) # Increased height for info
                
                # Header
                cv2.putText(canvas, "SIMILITUDES ENCONTRADAS (ESTABLE)", (140, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                
                for i, idx in enumerate(current_display_indices):
                    match = database[idx]
                    score = similarities[idx]
                    
                    m_img = cv2.imread(match['original_path'])
                    if m_img is None: continue
                    
                    m_img = cv2.resize(m_img, (280, 330))
                    
                    row = i // 2
                    col = i % 2
                    y_off = 50 + row * 400
                    x_off = 10 + col * 290
                    
                    canvas[y_off:y_off+330, x_off:x_off+280] = m_img
                    
                    color = (0, 255, 0) if score > 0.45 else (200, 200, 200)
                    cv2.putText(canvas, f"{i+1}. {match['year']}", (x_off, y_off+345), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                    cv2.putText(canvas, f"{match['name'][:24]}", (x_off, y_off+360), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
                    cv2.putText(canvas, f"{score*100:.1f}%", (x_off+220, y_off+345), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                # Add "Similar Characteristics" of identifying person below
                # InsightFace buffalo_l provides 'sex' (0:Female, 1:Male) and 'age'
                gender = "Masc" if main_face.sex == 1 else "Fem"
                age = int(main_face.age)
                traits_text = f"TUS RASGOS: {gender} | Edad aprox: {age} anos"
                cv2.putText(canvas, traits_text, (10, 830), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                
                cv2.imshow('Top 4 Matches', canvas)
            
            # Label on webcam frame
            best_score_live = similarities[best_idx]
            label = f"Buscando... Mejor match: {best_score_live*100:.1f}%"
            cv2.putText(frame, label, (bbox[0], bbox[1]-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        cv2.imshow('Busqueda en Boletines', frame)
        
        if not faces:
            history = []
            # We don't automatically close windows to allow user to see the result
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    webcam_search()
