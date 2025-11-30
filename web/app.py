"""Flask web application for Amazon Parser"""
import os
import threading
from flask import Flask, render_template, request, jsonify

from core.database import Database
from core.coordinator import Coordinator
from utils.logger import get_logger

logger = get_logger(__name__)

# Get the directory where this file is located
web_dir = os.path.dirname(os.path.abspath(__file__))

# Initialize Flask with correct template and static folders
app = Flask(
    __name__,
    template_folder=os.path.join(web_dir, 'templates'),
    static_folder=os.path.join(web_dir, 'static')
)

# Disable Flask request logging (we use our own logger)
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Configure Flask to properly close connections
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # 30 minutes

db = Database()

# Store progress for active tasks
task_progress = {}


def run_parsing_task(task_id: int, url: str, config: dict):
    """Run parsing task in background thread."""
    def progress_callback(message: str, percent: int):
        task_progress[task_id] = {
            'message': message,
            'percent': percent
        }
    
    try:
        coordinator = Coordinator(db)
        coordinator.run_parsing(task_id, url, config, progress_callback)
    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        db.update_task(task_id, status='failed', error_message=str(e))
    finally:
        # Clean up progress
        if task_id in task_progress:
            del task_progress[task_id]


@app.route('/')
def index():
    """Main page with form and task history."""
    recent_tasks = db.get_recent_tasks(limit=20)
    return render_template('index.html', tasks=recent_tasks)


@app.route('/start_parsing', methods=['POST'])
def start_parsing():
    """Start a new parsing task."""
    try:
        url = request.form.get('url', '').strip()
        
        if not url:
            response = jsonify({'error': 'URL is required'})
            response.headers['Connection'] = 'close'
            return response, 400
        
        if 'amazon.com' not in url.lower():
            response = jsonify({'error': 'Invalid Amazon URL'})
            response.headers['Connection'] = 'close'
            return response, 400
        
        # Build config from checkboxes
        config = {
            'images_hero': request.form.get('images_hero') == 'on',
            'images_gallery': request.form.get('images_gallery') == 'on',
            'images_aplus_product': request.form.get('images_aplus_product') == 'on',
            'images_aplus_brand': request.form.get('images_aplus_brand') == 'on',
            'images_aplus_manufacturer': request.form.get('images_aplus_manufacturer') == 'on',
            'text': request.form.get('text') == 'on',
            'reviews': request.form.get('reviews') == 'on',
        }
        
        # Validate that at least one option is selected
        has_images = any([
            config['images_hero'],
            config['images_gallery'],
            config['images_aplus_product'],
            config['images_aplus_brand'],
            config['images_aplus_manufacturer'],
        ])
        has_text = config['text']
        has_reviews = config['reviews']
        
        if not (has_images or has_text or has_reviews):
            response = jsonify({'error': 'Please select at least one option to parse'})
            response.headers['Connection'] = 'close'
            return response, 400
        
        # Create task in database
        task_id = db.create_task(url, config=config)
        
        # Initialize progress
        task_progress[task_id] = {'message': 'Starting...', 'percent': 0}
        
        # Start parsing in background thread
        thread = threading.Thread(
            target=run_parsing_task,
            args=(task_id, url, config),
            daemon=True
        )
        thread.start()
        
        logger.info(f"Started task #{task_id} for URL: {url[:50]}...")
        
        response = jsonify({
            'success': True,
            'task_id': task_id,
            'message': 'Parsing started'
        })
        response.headers['Connection'] = 'close'
        return response
        
    except Exception as e:
        logger.error(f"Failed to start parsing: {e}")
        response = jsonify({'error': str(e)})
        response.headers['Connection'] = 'close'
        return response, 500


@app.route('/task/<int:task_id>/status')
def task_status(task_id: int):
    """Get task status for AJAX polling."""
    task = db.get_task(task_id)
    
    if not task:
        response = jsonify({'error': 'Task not found'})
        response.headers['Connection'] = 'close'
        return response, 404
    
    # Get progress if task is running
    progress = task_progress.get(task_id, {})
    
    response = jsonify({
        'id': task['id'],
        'status': task['status'],
        'product_name': task.get('product_name'),
        'progress_message': progress.get('message', ''),
        'progress_percent': progress.get('percent', 0),
        'error_message': task.get('error_message'),
        'results': task.get('results')
    })
    response.headers['Connection'] = 'close'
    return response


@app.route('/task/<int:task_id>/results')
def task_results(task_id: int):
    """Get detailed task results."""
    results = db.get_task_results(task_id)
    
    if not results:
        response = jsonify({'error': 'Results not found'})
        response.headers['Connection'] = 'close'
        return response, 404
    
    response = jsonify(results)
    response.headers['Connection'] = 'close'
    return response


@app.route('/tasks')
def get_tasks():
    """Get recent tasks for AJAX refresh."""
    recent_tasks = db.get_recent_tasks(limit=20)
    
    # Format tasks for JSON response
    tasks = []
    for task in recent_tasks:
        tasks.append({
            'id': task['id'],
            'url': task['url'],
            'product_name': task.get('product_name'),
            'status': task['status'],
            'created_at': task['created_at'],
            'results': task.get('results'),
            'error_message': task.get('error_message'),
            'config': task.get('config', {})  # Include config to check if text parsing was selected
        })
    
    return jsonify(tasks)


if __name__ == '__main__':
    # This is only for direct execution, use run.py instead
    app.run(debug=True, port=5000, threaded=True)

