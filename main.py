from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import os
import sys
import shutil
import uuid
import csv
from pydantic import BaseModel
from agent_luis import agente_luis
from agent_felipe import agente_felipe

# Handling PyInstaller bundle path
if getattr(sys, 'frozen', False):
    base_dir = sys._MEIPASS
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="GeotaxPro AI")

# Mount the frontend static files
os.makedirs(os.path.join(base_dir, "temp"), exist_ok=True)
app.mount("/static", StaticFiles(directory=base_dir), name="static")
app.mount("/temp", StaticFiles(directory=os.path.join(base_dir, "temp")), name="temp")

@app.get("/")
async def read_root():
    return FileResponse(os.path.join(base_dir, "index.html"))

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "GeotaxPro Backend is running"}

# Store session statuses in memory
session_statuses = {}
# Store conversation history per session
chat_histories = {}

def background_processing_task(session_id: str, file_path: str, csv_path: str, output_video_path: str):
    try:
        import json
        calib_path = os.path.join(os.path.dirname(csv_path), "calibration.json")
        with open(calib_path) as f:
            calib = json.load(f)
        response = agente_luis.analizar_y_calibrar(file_path, csv_path, output_video_path, calib)
        fps = (response.get("results") or {}).get("fps")
        if fps:
            calib["fps"] = fps
            calib["frames_processed"] = (response.get("results") or {}).get("frames_processed")
            with open(calib_path, "w") as f:
                json.dump(calib, f)
        response["video_url"] = f"/temp/{session_id}/output.webm"
        session_statuses[session_id] = {
            "status": "completed",
            "data": response
        }
    except Exception as e:
        session_statuses[session_id] = {
            "status": "error",
            "message": str(e)
        }
    finally:
        # Delete video after processing to save space
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass

@app.post("/api/upload")
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...), pixels_per_cm: float = Form(50.0), target_cm: float = Form(10.0),
                       y_bottom: float = Form(None), y_top: float = Form(None), x_first: float = Form(None), x_last: float = Form(None),
                       n_tubes: int = Form(10), flies_per_tube: int = Form(10)):
    if None in (y_bottom, y_top, x_first, x_last):
        return JSONResponse(status_code=400, content={"message": "Faltan los clics de calibración (fondo, cima, primer y último tubo)."})
    session_id = str(uuid.uuid4())
    session_dir = os.path.join(base_dir, "temp", session_id)
    os.makedirs(session_dir, exist_ok=True)
    
    file_path = os.path.join(session_dir, file.filename)
    
    # Save the uploaded file
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    csv_path = os.path.join(session_dir, "results.csv")
    output_video_path = os.path.join(session_dir, "output.webm")
    
    calib_path = os.path.join(session_dir, "calibration.json")
    import json
    with open(calib_path, "w") as f:
        json.dump({"pixels_per_cm": pixels_per_cm, "target_cm": target_cm, "y_bottom": y_bottom, "y_top": y_top,
                   "x_first": x_first, "x_last": x_last, "n_tubes": n_tubes,
                   "flies_per_tube": flies_per_tube, "fps": 30.0}, f)
        
    # Initialize status and start background task
    session_statuses[session_id] = {"status": "processing"}
    background_tasks.add_task(background_processing_task, session_id, file_path, csv_path, output_video_path)
            
    return {"message": "Procesamiento iniciado de fondo.", "session_id": session_id}

@app.get("/api/status/{session_id}")
async def check_status(session_id: str):
    status = session_statuses.get(session_id)
    if not status:
        return JSONResponse(status_code=404, content={"message": "Sesión no encontrada"})
    return status

class ChatMessage(BaseModel):
    message: str
    session_id: str

@app.post("/api/chat")
async def chat_endpoint(chat: ChatMessage):
    session_dir = os.path.join(base_dir, "temp", chat.session_id)
    csv_path = os.path.join(session_dir, "results.csv")
    
    plot_filename = f"plot_{chat.session_id}.png"
    plot_path = os.path.join(base_dir, plot_filename)
    
    # Initialize history if not exists
    if chat.session_id not in chat_histories:
        chat_histories[chat.session_id] = []
        
    # Read calibration if exists
    calib_path = os.path.join(session_dir, "calibration.json")
    pixels_per_cm = 50.0
    target_cm = 10.0
    if os.path.exists(calib_path):
        import json
        with open(calib_path, "r") as f:
            c = json.load(f)
            pixels_per_cm = c.get("pixels_per_cm", 50.0)
            target_cm = c.get("target_cm", 10.0)
            fps = c.get("fps", 30.0)
            y_bottom = c.get("y_bottom")
    else:
        fps, y_bottom = 30.0, None
            
    try:
        respuesta = agente_felipe.procesar_consulta(chat.message, csv_path, plot_path, chat_histories[chat.session_id], pixels_per_cm, target_cm, fps, y_bottom)
        
        graph_data = None
        if respuesta["grafica"] == "frontend_render":
            with open(csv_path, newline='') as f:
                reader = csv.DictReader(f)
                graph_data = list(reader)
                
        return {
            "response": respuesta["respuesta"], 
            "graph_url": "frontend_render" if respuesta["grafica"] == "frontend_render" else None,
            "graph_data": graph_data,
            "raw_metrics": respuesta.get("raw_metrics")
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@app.get("/api/tubes/{session_id}")
async def tubes_endpoint(session_id: str):
    import json
    from tubes import metricas_por_tubo
    session_dir = os.path.join(base_dir, "temp", session_id)
    csv_path = os.path.join(session_dir, "results.csv")
    calib_path = os.path.join(session_dir, "calibration.json")
    if not os.path.exists(csv_path) or not os.path.exists(calib_path):
        return JSONResponse(status_code=404, content={"message": "No hay datos procesados para este video."})
    with open(calib_path) as f:
        calib = json.load(f)
    try:
        return metricas_por_tubo(csv_path, calib)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"message": str(e)})

class StatsRequest(BaseModel):
    grupos: dict
    alpha: float = 0.05
    unidad: str = "cm"

@app.post("/api/stats")
async def stats_endpoint(req: StatsRequest):
    from stats_engine import analizar
    try:
        return analizar(req.grupos, req.alpha, req.unidad)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"Error en el análisis: {e}"})

if __name__ == "__main__":
    import uvicorn
    import threading
    import webview
    
    def start_server():
        uvicorn.run(app, host="127.0.0.1", port=7860)
        
    t = threading.Thread(target=start_server)
    t.daemon = True
    t.start()
    
    webview.create_window('GeotaxPro AI', 'http://127.0.0.1:7860', width=1200, height=800)
    webview.start()
