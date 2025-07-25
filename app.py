from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from PIL import Image
import pytesseract
from io import BytesIO
import cv2
import numpy as np
import re
import pandas as pd

app = Flask(__name__)

# ====== IMAGE PROCESSING ======
def process_image(img):
    pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
    img = np.array(img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 11, 2)
    kernel = np.ones((1, 1), np.uint8)
    processed_image_cv = cv2.dilate(thresh, kernel, iterations=1)

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        processed_image_cv, 8, cv2.CV_32S)
    min_component_size = 30
    filtered_image = np.zeros_like(processed_image_cv)

    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area > min_component_size:
            filtered_image[labels == i] = 255

    kernel_close = np.ones((1, 1), np.uint8)
    processed_image_cv = cv2.morphologyEx(filtered_image, cv2.MORPH_CLOSE, kernel_close, iterations=1)
    processed_image_cv = cv2.bitwise_not(processed_image_cv)
    text = pytesseract.image_to_string(processed_image_cv, lang='eng',
                                       config='--psm 8 --oem 3 -c tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')[:5]
    return text

def get_span_text_by_id(soup, id_name):
    span = soup.find('span', {'id': id_name})
    return span.text.strip() if span else None

def get_vehicle_info(txtBienDK, TxtSoTem):
    try:
        session = requests.Session()
        url = 'http://app.vr.org.vn/ptpublic/thongtinptpublic.aspx'
        base_url = "http://app.vr.org.vn"
        html_url = base_url + "/ptpublic/thongtinptpublic.aspx"

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": html_url
        }

        res = session.get(url)
        soup = BeautifulSoup(res.text, 'html.parser')

        viewstate = soup.find(id="__VIEWSTATE")['value']
        viewstategen = soup.find(id="__VIEWSTATEGENERATOR")['value']
        eventvalidation = soup.find(id="__EVENTVALIDATION")['value']

        captcha_url = soup.find("img", {"id": "captchaImage"})['src']
        captcha_full_url = base_url + "/ptpublic/" + captcha_url
        captcha_img = session.get(captcha_full_url)
        img = Image.open(BytesIO(captcha_img.content))

        post_data = {
            '__VIEWSTATE': viewstate,
            '__VIEWSTATEGENERATOR': viewstategen,
            '__EVENTVALIDATION': eventvalidation,
            'txtBienDK': txtBienDK,
            'TxtSoTem': TxtSoTem,
            'txtCaptcha': process_image(img),
            'CmdTraCuu': 'Tra cứu'
        }

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': url,
            'User-Agent': 'Mozilla/5.0'
        }

        res_post = session.post(url, data=post_data, headers=headers)
        soup1 = BeautifulSoup(res_post.text, 'html.parser')

        nhan_hieu = get_span_text_by_id(soup1, 'txtNhanHieu')
        so_khung = get_span_text_by_id(soup1, 'txtSoKhung')
        so_may = get_span_text_by_id(soup1, 'txtSoMay')
        return pd.Series([nhan_hieu, so_khung, so_may], index=["HangXe", "SoKhung", "SoMay"])

    except Exception as e:
        return pd.Series([None, None, None], index=["HangXe", "SoKhung", "SoMay"])

def get_vehicle_info_retry(txtBienDK, TxtSoTem, max_retries=5):
    for attempt in range(max_retries):
        result = get_vehicle_info(txtBienDK, TxtSoTem)
        if result.notna().all():
            return result
    return pd.Series([None, None, None], index=["HangXe", "SoKhung", "SoMay"])

def split_text_number(text):
    match = re.match(r"([A-Za-z]+)(\d+)", text)
    if match:
        return match.group(1) + "-" + match.group(2)
    return text

def preprocess_data(DK, BSX, MauBS):
    DK = DK.replace("-", "").replace(" ", "")
    DK = split_text_number(DK)
    BSX = BSX.replace("-", "").replace(" ", "") + MauBS[0]
    return get_vehicle_info_retry(DK, BSX)

@app.route("/")
def index():
    return "Vehicle Lookup API is running."

@app.route("/lookup", methods=["GET"])
def lookup():
    DK = request.args.get("DK")
    BSX = request.args.get("BSX")
    MauBS = request.args.get("MauBS")

    if not DK or not BSX or not MauBS:
        return jsonify({"error": "Thiếu tham số DK, BSX, hoặc MauBS"}), 400

    result = preprocess_data(DK, BSX, MauBS)

    if result.notna().all():
        return jsonify(result.to_dict())
    else:
        return jsonify({"error": "Không tra cứ
