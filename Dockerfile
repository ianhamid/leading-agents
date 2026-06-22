FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY macro_agent.py /app/
COPY tape_reader_agent_v2.py /app/
COPY tape_reader_agent_v3.py /app/
COPY setup.py /app/
CMD ["python3", "tape_reader_agent_v2.py"]