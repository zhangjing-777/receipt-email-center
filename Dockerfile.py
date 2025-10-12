# 安装 Python 和依赖
FROM python:3.11-slim

# 设定工作目录
WORKDIR /app

# 拷贝依赖
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# 拷贝代码 
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

