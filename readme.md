### Setup 26/10/2025

1. Clone the repository:

   ```
   git clone <repository-url>
   cd <repository-folder>
   ```

2. Create a virtual environment:

   ```
   python -m venv venv
   ```

3. Activate the virtual environment:

   - Windows:
     ```
     venv\Scripts\activate || venv\Scripts\activate.bat
     ```
   - macOS/Linux:
     ```
     source venv/bin/activate
     ```

4. Install dependencies:

   ```
   pip install -r requirements.txt
   ```

5. Change the directory to:

   ```
   cd backend
   ```

6. Run the application:
   ```
   uvicorn main:app --reload
   ```

### Frontend (Next.js)

1. Navigate to the frontend directory:

   ```
   cd <frontend-name>
   ```

2. Install dependencies:

   ```
   npm install
   ```

3. Run the development server:
   ```
   npm run dev
   ```

The application will be available at:

- Frontend: [http://localhost:3000](http://localhost:3000)
- Backend: [http://localhost:8000](http://localhost:8000) and
- [http://localhost:8000/docs](http://localhost:8000/docs) to access the backend documentation
 t