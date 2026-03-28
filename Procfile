web: sh -c 'python3 -m gunicorn web.app:app --bind 0.0.0.0:${PORT:-8000} --workers 2 --threads 4 --timeout 120 --keep-alive 5 --max-requests 1000 --max-requests-jitter 100 --preload'
