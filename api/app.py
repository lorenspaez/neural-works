from flask import Flask, render_template, request, redirect, url_for, jsonify
from datetime import datetime as dt, timedelta
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
from sqlalchemy import DateTime, desc
from flask_migrate import Migrate
import pandas as pd
from shapely import geometry, wkt
import requests

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///trips.db"  # SQLite as database
db = SQLAlchemy(app)
migrate = Migrate(app, db)


class Trip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    region = db.Column(db.String(100))
    origin_coord = db.Column(db.String(100))
    destination_coord = db.Column(db.String(100))
    datetime = db.Column(DateTime, default=None, server_default=func.now())
    datasource = db.Column(db.String(100))


@app.route("/")
def index():
    return render_template("index.html")


def notify_data_ingestion_state(region, datasource):
    try:
        # Here you should add you url where you want to receive notifications
        notification_url = "http://127.0.0.1:5000/notifications"

        # Data to send in the POST request
        data = {
            "region": region,
            "datasource": datasource,
            "status": "Ingestion Completed",
        }

        # Make the HTTP POST request to notify the state
        response = requests.post(notification_url, json=data)

        # Check if the notification was successful (status code 200)
        if response.status_code == 200:
            return True
        else:
            print(
                f"Failed to notify data ingestion state. Status code: {response.status_code}"
            )
            return False

    except Exception as e:
        print(f"Error notifying data ingestion state: {str(e)}")
        return False


# Define a route to handle notifications
@app.route("/notifications", methods=["POST"])
def receive_notification():
    try:
        # Get the JSON data from the request
        data = request.get_json()
        region = data.get("region")
        datasource = data.get("datasource")
        status = data.get("status")

        print(
            f"Received notification for region: {region}, datasource: {datasource}, status: {status}"
        )

        return jsonify({"message": "Notification received successfully"}), 200

    except Exception as e:
        print(f"Error handling notification: {str(e)}")
        return jsonify({"message": "Error handling notification"}), 500


@app.route("/create_trip", methods=["GET", "POST"])
def create_trip():
    if request.method == "POST":
        if request.content_type == "application/json":
            # Handle JSON data
            data = request.json
            region = data.get("region")
            origin_coord = data.get("origin_coord")
            destination_coord = data.get("destination_coord")
            datasource = data.get("datasource")
        else:
            region = request.form["region"]
            origin_coord_str = request.form["origin_coord"]
            destination_coord_str = request.form["destination_coord"]
            datasource = request.form["datasource"]

            # Parse the coordinates from the user input
            origin_coord = wkt.loads(f"POINT ({origin_coord_str})")
            destination_coord = wkt.loads(f"POINT ({destination_coord_str})")

        # Convert the Shapely objects to WKT strings
        origin_coord_wkt = origin_coord.wkt
        destination_coord_wkt = destination_coord.wkt

        trip = Trip(
            region=region,
            origin_coord=origin_coord_wkt,
            destination_coord=destination_coord_wkt,
            datasource=datasource,
        )
        db.session.add(trip)
        db.session.commit()

        # Notify the state of data ingestion
        if notify_data_ingestion_state(region, datasource):
            return render_template(
                "create_trip.html",
                message="Viaje creado exitosamente y estado de ingesta notificado.",
            )
        else:
            return render_template(
                "create_trip.html",
                message="Viaje creado exitosamente, pero falló la notificación de estado de ingesta.",
            )
    return render_template("create_trip.html")


@app.route("/trips", methods=["GET"])
def trips():
    trips = Trip.query.order_by(desc(Trip.datetime)).limit(25).all()
    return render_template("trips.html", trips=trips)


@app.route("/grouped_trips", methods=["GET"])
def grouped_trips():
    filtered_trips = Trip.query.all()

    # Create a new column for 6-hour intervals
    intervals = pd.cut(
        [trip.datetime.hour for trip in filtered_trips],
        bins=range(0, 25, 6),
        labels=["00:00 - 05:59", "06:00 - 11:59", "12:00 - 17:59", "18:00 - 23:59"],
    )
    [
        setattr(trip, "interval", interval)
        for trip, interval in zip(filtered_trips, intervals)
    ]

    # Calculate the weekly average count of trips per region and interval
    result = {}  # A dictionary to store the results

    for trip in filtered_trips:
        region = trip.region
        interval = trip.interval
        if (region, interval) not in result:
            result[(region, interval)] = {"count": 1, "trip_ids": [trip.id]}
        else:
            result[(region, interval)]["count"] += 1
            result[(region, interval)]["trip_ids"].append(trip.id)

    # Create a list of results
    average_results = [
        {
            "region": region,
            "interval": interval,
            "count": data["count"],
            "trip_ids": data["trip_ids"],
        }
        for (region, interval), data in result.items()
    ]
    return render_template("grouped_trips.html", trips=average_results)


@app.route("/average_trips", methods=["GET", "POST"])
def average_trips():
    if request.method == "POST":
        region = request.form["region"]
        point1_str = request.form["point1"]
        point2_str = request.form["point2"]
        point3_str = request.form["point3"]
        point4_str = request.form["point4"]

        # Parse the coordinates from the user input as Shapely objects
        point1 = wkt.loads(f"POINT ({point1_str})")
        point2 = wkt.loads(f"POINT ({point2_str})")
        point3 = wkt.loads(f"POINT ({point3_str})")
        point4 = wkt.loads(f"POINT ({point4_str})")

        # Define the bounding box coordinates as a polygon
        bounding_box = geometry.Polygon([point1, point2, point3, point4])

        # Filter trips by region and coordinates that are inside the bounding box
        trips = Trip.query.filter_by(region=region).all()

        # Create a list of dates and times for the trips that are inside the bounding box
        datetime_list = []
        for trip in trips:
            trip_point = wkt.loads(
                trip.origin_coord
            )  # Parse trip origin_coord as a Shapely object
            if bounding_box.contains(trip_point):
                datetime_list.append(trip.datetime)

        if not datetime_list:
            return (
                "No se encontraron fechas de viajes válidas para calcular el promedio"
            )

        # Create a pandas DataFrame from the list of dates and times
        df = pd.DataFrame({"datetime": datetime_list})

        # Ensure that 'datetime' is treated as a date and time object
        df["datetime"] = pd.to_datetime(df["datetime"])

        # Create a new 'week' column to store the week and year
        df["week"] = df["datetime"].dt.strftime("%U-%Y")

        # Calculate the weekly average using groupby and mean
        weekly_average = df.groupby("week").size().mean()

        return render_template("average_trips.html", weekly_average=weekly_average)

    return render_template("average_trips.html")


@app.route("/load_data", methods=["GET"])
def load_data():
    df = pd.read_csv("trips.csv")

    try:
        for index, row in df.iterrows():
            # Convert the date and time string from the CSV into a datetime object
            datetime_obj = dt.strptime(row["datetime"], "%Y-%m-%d %H:%M:%S")

            trip = Trip(
                region=row["region"],
                origin_coord=row["origin_coord"],
                destination_coord=row["destination_coord"],
                datetime=datetime_obj,  # Use the datetime object instead of the string
                datasource=row["datasource"],
            )
            db.session.add(trip)

        db.session.commit()
        return "Datos cargados exitosamente en la base de datos."
    except Exception as e:
        db.session.rollback()
        return f"Error al cargar datos en la base de datos: {str(e)}"
    finally:
        db.session.close()


if __name__ == "__main__":
    db.create_all()
    app.run(debug=True)
