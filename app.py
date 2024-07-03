import os
import pathlib
from flask import Flask,render_template,session,redirect,abort,request,jsonify
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
import requests
from pip._vendor import cachecontrol
import google.auth.transport.requests

#model packeges
import tensorflow as tf
from keras import layers
import numpy as np
import pandas as pd

app = Flask("youtube comments project")

app.config["SECRET_KEY"] = os.getenv("CLIENT_SECRET")

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

GOOGLE_CLIENT_ID = os.getenv("CLIENT_ID")

client_secrets_file = os.path.join(pathlib.Path(__file__).parent , "client_secret.json")

flow = Flow.from_client_secrets_file(
    client_secrets_file,
    scopes=["https://www.googleapis.com/auth/userinfo.profile", 
            "https://www.googleapis.com/auth/userinfo.email", "openid","https://www.googleapis.com/auth/youtube.force-ssl"],
    redirect_uri="http://localhost:3000/auth/google/callback"
)

GET_COMMENTS_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
REMOVE_COMMENTS_URL = "https://www.googleapis.com/youtube/v3/comments/setModerationStatus"

def login_is_required(function):
    def wrapper(*args, **kwargs):
        if "google_id" not in session:
            return '<h1>login using ur google account<h1> <br> <a href = "/login"><button> login </button></a>'  # Authorization required
        else:
            return function()

    return wrapper

@app.route("/login")
def login():
    session.clear()
    authorization_url,state = flow.authorization_url()
    print(session)
    session["state"] = state
    return redirect(authorization_url)

@app.route("/auth/google/callback")
def callback():
    flow.fetch_token(authorization_response=request.url)

    credentials = flow.credentials
    request_session = requests.session()
    cached_session = cachecontrol.CacheControl(request_session)
    token_request = google.auth.transport.requests.Request(session=cached_session)
    id_info = id_token.verify_oauth2_token(
        id_token=credentials._id_token,
        request=token_request,
        audience=GOOGLE_CLIENT_ID
    )
    session["Access_token"] = credentials.token
    
    session["google_id"] = id_info.get("sub")
    session["name"] = id_info.get("name")
    return redirect("/protected_area")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/protected_area")
@login_is_required
def protected_area():
    data = {
        "name": session["name"],
    }
    return render_template("home.html", data=data)

@app.route("/submit",methods=["POST"])
def submit():
    video_url = request.form.get("urln")
    print(video_url)
    video_id = video_url.split("v=")[1]
    if "&" in video_id:
        video_id = video_id.split("&")[0]
    print(video_id)
    params = {
        "part": "id,replies,snippet",
        "videoId": video_id,
        "key": os.getenv("API_KEY")
    }
    response = requests.get(GET_COMMENTS_URL,params=params)
    #return response.json()
    if response.status_code == 200:
        data = response.json()
        items = data.get("items")
        comments = []
        for item in items:
            comments.append({
                "comment_text": item["snippet"].get("topLevelComment").get("snippet").get("textDisplay"),
                "comment_id": item["snippet"].get("topLevelComment").get("id")
            })
            #print("comment text "+item["snippet"].get("topLevelComment").get("snippet").get("textDisplay")+" comment id "+item["snippet"].get("topLevelComment").get("id"))
        session["comments"] = comments
        return redirect("/process_comments")
    else:
        print(response)
    return redirect("/protected_area")

@app.route("/process_comments",methods=["GET","POST"])
def process_cmts():
    cmts = session.get("comments")
    model = tf.keras.models.load_model('python-model/toxicity_colab.h5')
    MAX_FEATURES = 200000 # number of words in the vocab
    df = pd.read_csv('new_train - train.csv')
    X = df['comment_text']
    vectorizer = layers.TextVectorization(max_tokens=MAX_FEATURES,
                               output_sequence_length=1800,
                               output_mode='int')
    vectorizer.adapt(X.values)
    for comment in cmts:
        vectorized_comment = vectorizer([comment["comment_text"]])
        results = model.predict(vectorized_comment)
    
        res = {}
        comment["prediction"] = False
        for idx, col in enumerate(df.columns[2:]):
            if results[0][idx]>0.5:
                comment["prediction"] = True
                break
    session["comments"] = cmts
    return redirect("/remove_comments")

@app.route("/remove_comments",methods=["GET","POST"])
def remove_comments():
    cmts = session.get("comments")
    print(session.get("Access_token"))
    for comment in cmts:
        if comment["prediction"]:
            print(comment["comment_text"])
            params = {
                "id": comment["comment_id"],
                "moderationStatus": "rejected"
            }
            headers = {
                "Authorization": f"Bearer {session.get('Access_token')}"
            }
            response = requests.post(REMOVE_COMMENTS_URL,params=params,headers=headers)
            if response.status_code != 204:
                print(response)
            else:
                print("Comment deleted successfully!")
    return redirect("/protected_area")



if __name__ == "__main__":
    app.run(debug=True,port=3000)