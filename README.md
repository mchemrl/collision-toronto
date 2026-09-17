# Closer Look At Toronto's Collision

An interactive dashboard exploring road collisions in Toronto.

The main goal is to highlight how pedestrians and cyclists are particularly affected by road collisions, present key collision statistics, and explore potential solutions. The dashboard is intended to be useful for government, NGOs, activists, and anyone interested in road safety.

## Run locally

### 1. Clone the repository

```bash
git clone https://github.com/mchemrl/collision-toronto/
cd collision-toronto
```

###2. Start the backend

In one terminal:

```bash
cd backend
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

### 3. Start the frontend

In another terminal, from the project root:
```bash
python -m http.server 5500
```
Open:

http://localhost:5500
