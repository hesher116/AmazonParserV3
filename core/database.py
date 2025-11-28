"""SQLite database for task history"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from contextlib import contextmanager

from config.settings import Settings
from utils.logger import get_logger

logger = get_logger(__name__)


class Database:
    """SQLite database manager for task history."""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or Settings.DATABASE_PATH
        self._init_db()
    
    def _init_db(self):
        """Initialize database and create tables if needed."""
        with self._get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    product_name TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    results_json TEXT,
                    error_message TEXT,
                    config_json TEXT
                )
            ''')
            conn.commit()
        logger.info(f"Database initialized: {self.db_path}")
    
    @contextmanager
    def _get_connection(self):
        """Get database connection context manager."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def create_task(
        self, 
        url: str, 
        product_name: str = None,
        config: Dict = None
    ) -> int:
        """
        Create a new parsing task.
        
        Args:
            url: Amazon product URL
            product_name: Product name (optional)
            config: Task configuration (selected agents)
            
        Returns:
            Task ID
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                '''
                INSERT INTO tasks (url, product_name, status, config_json)
                VALUES (?, ?, 'pending', ?)
                ''',
                (url, product_name, json.dumps(config) if config else None)
            )
            conn.commit()
            task_id = cursor.lastrowid
            logger.info(f"Created task #{task_id} for URL: {url[:50]}...")
            return task_id
    
    def update_task(
        self,
        task_id: int,
        status: str = None,
        product_name: str = None,
        results: Dict = None,
        error_message: str = None
    ):
        """
        Update task status and results.
        
        Args:
            task_id: Task ID
            status: New status (pending/running/completed/failed)
            product_name: Product name
            results: Results dictionary
            error_message: Error message if failed
        """
        updates = []
        params = []
        
        if status:
            updates.append("status = ?")
            params.append(status)
            if status == 'completed':
                updates.append("completed_at = ?")
                params.append(datetime.now().isoformat())
        
        if product_name:
            updates.append("product_name = ?")
            params.append(product_name)
        
        if results:
            updates.append("results_json = ?")
            try:
                # Truncate large results to prevent database errors
                results_str = json.dumps(results, default=str)  # Use default=str for non-serializable objects
                # SQLite TEXT limit is ~1GB, but we'll limit to 10MB for safety
                max_size = 10 * 1024 * 1024  # 10MB
                if len(results_str) > max_size:
                    logger.warning(f"Results too large ({len(results_str)} bytes), truncating...")
                    # Keep only essential summary data
                    truncated_results = {
                        'product_name': results.get('product_name'),
                        'images': results.get('images', {}),
                        'reviews_count': results.get('reviews_count', 0),
                        'qa_count': results.get('qa_count', 0),
                        'variants_count': results.get('variants_count', 0),
                        'processing_time_seconds': results.get('processing_time_seconds'),
                        'processing_time_formatted': results.get('processing_time_formatted'),
                        'errors': results.get('errors', [])[:10]  # Keep only first 10 errors
                    }
                    results_str = json.dumps(truncated_results, default=str)
                params.append(results_str)
            except (TypeError, ValueError) as e:
                logger.error(f"Failed to serialize results to JSON: {e}")
                # Save minimal error info instead
                params.append(json.dumps({'error': 'Failed to serialize results', 'error_type': str(type(e).__name__)}))
        
        if error_message:
            updates.append("error_message = ?")
            params.append(error_message)
        
        if not updates:
            return
        
        params.append(task_id)
        
        with self._get_connection() as conn:
            conn.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
                params
            )
            conn.commit()
            logger.debug(f"Updated task #{task_id}: status={status}")
    
    def get_task(self, task_id: int) -> Optional[Dict]:
        """
        Get task by ID.
        
        Args:
            task_id: Task ID
            
        Returns:
            Task dictionary or None
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (task_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
            return None
    
    def get_recent_tasks(self, limit: int = 20) -> List[Dict]:
        """
        Get recent tasks.
        
        Args:
            limit: Maximum number of tasks to return
            
        Returns:
            List of task dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM tasks 
                ORDER BY created_at DESC 
                LIMIT ?
                """,
                (limit,)
            )
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]
    
    def get_task_results(self, task_id: int) -> Optional[Dict]:
        """
        Get task results.
        
        Args:
            task_id: Task ID
            
        Returns:
            Results dictionary or None
        """
        task = self.get_task(task_id)
        if task and task.get('results_json'):
            try:
                return json.loads(task['results_json'])
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Failed to parse results JSON for task {task_id}: {e}")
                return None
        return None
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        """Convert database row to dictionary."""
        result = dict(row)
        
        # Parse JSON fields
        if result.get('results_json'):
            try:
                result['results'] = json.loads(result['results_json'])
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Failed to parse results JSON for task {result.get('id')}: {e}")
                result['results'] = None
        else:
            result['results'] = None
        
        if result.get('config_json'):
            try:
                result['config'] = json.loads(result['config_json'])
            except json.JSONDecodeError:
                result['config'] = None
        else:
            result['config'] = None
        
        return result
    
    def delete_task(self, task_id: int) -> bool:
        """
        Delete task by ID.
        
        Args:
            task_id: Task ID
            
        Returns:
            True if deleted
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM tasks WHERE id = ?",
                (task_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def cleanup_old_tasks(self, days: int = 30) -> int:
        """
        Delete tasks older than specified days.
        
        Args:
            days: Number of days to keep
            
        Returns:
            Number of deleted tasks
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM tasks 
                WHERE created_at < datetime('now', ?)
                """,
                (f'-{days} days',)
            )
            conn.commit()
            count = cursor.rowcount
            if count > 0:
                logger.info(f"Cleaned up {count} old tasks")
            return count

