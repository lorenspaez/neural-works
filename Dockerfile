FROM python:3.9

WORKDIR /app

COPY . /app

RUN pip install -r requirements.txt

RUN flask db init
RUN flask db migrate -m "Trip table created"
RUN flask db upgrade

EXPOSE 5000

CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]
