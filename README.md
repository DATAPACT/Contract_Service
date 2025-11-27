# contract-service
Repository for the FastAPI implementation of a Contract Service that enables 1) the creation of contracts,  2) the storage and management of contracts and 3) functions to operate for specific contracts.





## Docker Setup Instructions

* Configure the files as mentioned above
* Build and run the docker container as usual
  * run MongoDB in Docker with your app
    * build docker-compose.yml file
    * docker compose up --build 
    * or  docker compose up -d --build (running on background)
    * docker compose down

  
* The API documentation will then be available under the `/docs` sub path, such as `http://127.0.0.1:8006/docs`

## Manual Installation Instructions
If you are not using docker, you can run the project as follows:
* Configure the files as mentioned above
* Install MongoDB database
* Install required libraries using `pip install -r requirements.txt`
* Run FastAPI  `python contract_service_api.py` from the project directory
* See the API here `http://127.0.0.1:8006/docs`

