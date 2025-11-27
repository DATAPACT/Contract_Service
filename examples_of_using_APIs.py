import os
from fastapi import HTTPException

import requests, shutil
from dotenv import load_dotenv
load_dotenv()

BASE_URL = os.getenv("API_CONTRACT_SERVICE_URL")

json_data = {
  "client_optional_info": {
    "negotiation_id": "68878520a62982a292b58241",
    "policy_id": "6895fc69c1a112e2ca522832",
    "type": "offer",
    "updated_at": "2025-09-09T15:19:28.555787"
  },
  "contract_type": "dsa",
  "validity_period": 24,
  "notice_period": 90,
  "contacts": {
    "consumer": {
      "_id": "68821fc7eeea3fe76612e027",
      "name": "upcast_david",
      "type": "consumer",
      "username_email": "david@example.com",
      "organization": "Consumer GmbH",
      "distinctive_title": "CONSUMER",
      "incorporation": "Germany",
      "registered_address": "2 Verbraucherplatz, Berlin, DE",
      "address": "2 Verbraucherplatz, Berlin, DE",
      "vat_no": "DE999999999",
      "contact_person": "David Glass",
      "role": "Head of Data",
      "phone": "+49 30 9876 5432",
      "consumer_id": "68821fc7eeea3fe76612e027"
    },
    "provider": {
      "_id": "68821ed6eeea3fe76612e026",
      "name": "upcast_miao",
      "type": "provider",
      "username_email": "miao@example.com",
      "organization": "Provider Ltd",
      "distinctive_title": "PROVIDER",
      "incorporation": "England and Wales",
      "registered_address": "1 Provider Way, London, UK",
      "address": "1 Provider Way, London, UK",
      "vat_no": "GB123456789",
      "contact_person": "Miao Da Hu",
      "role": "Data Protection Officer",
      "phone": "+44 20 1234 5678",
      "provider_id": "68878520a62982a292b5823f"
    }
  },
  "resource_description": {
    "title": "dafa",
    "price": "59.99",
    "uri": "Data",
    "policy_url": "",
    "environmental_cost_of_generation": {
      "additionalProp1": "333",
      "additionalProp2": "555"
    },
    "environmental_cost_of_serving": {
      "additionalProp1": "666",
      "additionalProp2": "777"
    },
    "description": "This is a description of Product ABC.",
    "type_of_data": "",
    "data_format": "",
    "data_size": "",
    "tags": "electronics, gadgets, technology"
  },
  "definitions": {
    "Data Processor": "A ‘processor’ means a natural or legal person, public authority, agency or other body which processes personal data on behalf of the controller. (Please refer to https://w3id.org/dpv/dpv-owl#DataProcessor for more details.)\n",
    "anonymize": "To anonymize all or parts of the Asset.. For example, to remove identifying particulars for statistical or for other comparable purposes, or to use the Asset without stating the author/source. (Please refer to http://www.w3.org/ns/odrl/2/anonymize for more details.)\n",
    "Communication Management": "Communication Management refers to purposes associated with providing or managing communication activities e.g. to send an email for notifying some information. This purpose by itself does not sufficiently and clearly indicate what the communication is about. As such, it is recommended to combine it with another purpose to indicate the application. For example, Communication of Payment. (Please refer to https://w3id.org/dpv#CommunicationManagement for more details.)\n",
    "economic Indicators": "The definition does not exist in http://example.org/datasets/economicIndicators. Please insert the definition.\n",
    "Legal Entity": "A human or non-human 'thing' that constitutes as an entity and which is recognised and defined in law (Please refer to https://w3id.org/dpv/dpv-owl#LegalEntity for more details.)\n",
    "derive": "To create a new derivative Asset from this Asset and to edit or modify the derivative.. A new asset is created and may have significant overlaps with the original Asset. (Note that the notion of whether or not the change is significant enough to qualify as a new asset is subjective). To the derived Asset a next policy may be applied. (Please refer to http://www.w3.org/ns/odrl/2/derive for more details.)\n",
    "Credit Checking": "Purposes associated with monitoring, performing, or assessing credit worthiness or solvency (Please refer to https://w3id.org/dpv#CreditChecking for more details.)\n",
    "aggregate": "To use the Asset or parts of it as part of a composite collection. (Please refer to http://www.w3.org/ns/odrl/2/aggregate for more details.)\n",
    "Maintain Credit Rating Database": "Purposes associated with maintaining a Credit Rating Database (Please refer to https://w3id.org/dpv#MaintainCreditRatingDatabase for more details.)\n",
    "Authority": "An authority with the power to create or enforce laws, or determine their compliance. (Please refer to https://w3id.org/dpv/dpv-owl#Authority for more details.)\n",
    "Distribution": "Distribution, public display, and publicly performance.. This term is defined by Creative Commons. (Please refer to http://creativecommons.org/ns#Distribution for more details.)\n",
    "Counterterrorism": "The definition does not exist in https://w3id.org/dpv#Counterterrorism. Please insert the definition.\n",
    "Consumer": "Data subjects that consume goods or services for direct use (Please refer to https://w3id.org/dpv/dpv-owl#Consumer for more details.)\n",
    "Counter Money Laundering": "Purposes associated with detection, prevention, and mitigation of mitigate money laundering (Please refer to https://w3id.org/dpv#CounterMoneyLaundering for more details.)\n"
  },

  "custom_clauses": {
    "Data Sharing Rules": [
      "Party B  in duty bound to   Party A to  perform  the distribution action on the economic indicators dataset, specifically  for the purpose of counterterrorism. Party B shall confirm execution of the distribution action by providing certification or proof upon request."
    ],

     "Data Protection": [
      "Party B  in duty bound to   Party A to  perform  the distribution action on the economic indicators dataset, specifically  for the purpose of counterterrorism. Party B shall confirm execution of the distribution action by providing certification or proof upon request."
    ]
  },
  "odrl": {
    "permission": [
      {
        "action": "http://www.w3.org/ns/odrl/2/anonymize",
        "assignee": "https://w3id.org/dpv/dpv-owl#DataProcessor",
        "target": "http://example.org/datasets/economicIndicators",
        "constraint": [
          {
            "leftOperand": "purpose",
            "operator": "http://www.w3.org/ns/odrl/2/eq",
            "rightOperand": "https://w3id.org/dpv#CommunicationManagement"
          }
        ]
      }
    ],
    "obligation": [
      {
        "action": "http://www.w3.org/ns/odrl/2/derive",
        "assignee": "https://w3id.org/dpv/dpv-owl#LegalEntity",
        "target": "http://example.org/datasets/economicIndicators",
        "constraint": [
          {
            "leftOperand": "purpose",
            "operator": "http://www.w3.org/ns/odrl/2/eq",
            "rightOperand": "https://w3id.org/dpv#CreditChecking"
          }
        ]
      },
      {
        "action": "http://www.w3.org/ns/odrl/2/aggregate",
        "assignee": "https://w3id.org/dpv/dpv-owl#LegalEntity",
        "target": "http://example.org/datasets/economicIndicators",
        "constraint": [
          {
            "leftOperand": "purpose",
            "operator": "http://www.w3.org/ns/odrl/2/eq",
            "rightOperand": "https://w3id.org/dpv#MaintainCreditRatingDatabase"
          }
        ]
      }
    ],
    "duty": [
      {
        "action": "http://creativecommons.org/ns#Distribution",
        "assignee": "https://w3id.org/dpv/dpv-owl#Authority",
        "target": "http://example.org/datasets/economicIndicators",
        "constraint": [
          {
            "leftOperand": "purpose",
            "operator": "http://www.w3.org/ns/odrl/2/eq",
            "rightOperand": "https://w3id.org/dpv#Counterterrorism"
          }
        ]
      },
      {
        "action": "http://www.w3.org/ns/odrl/2/derive",
        "assignee": "https://w3id.org/dpv/dpv-owl#Consumer",
        "target": "http://example.org/datasets/economicIndicators",
        "constraint": [
          {
            "leftOperand": "purpose",
            "operator": "http://www.w3.org/ns/odrl/2/eq",
            "rightOperand": "https://w3id.org/dpv#CounterMoneyLaundering"
          }
        ]
      }
    ],
    "uid": "http://example.org/policy-0c464f86-af9e-4a60-8708-d32cad8dee13",
    "@context": [
      "http://www.w3.org/ns/odrl.jsonld",
      {
        "dcat": "http://www.w3.org/ns/dcat#",
        "dpv": "https://w3id.org/dpv/dpv-owl#"
      }
    ],
    "@type": "Policy"
  },
  "dpw": {
    "@context": {
      "upcast": "https://www.upcast-project.eu/upcast-vocab/1.0/",
      "idsa-core": "https://w3id.org/idsa/core/",
      "dct": "http://purl.org/dc/terms/",
      "wmo": "http://www.ict-abovo.eu/ontologies/WorkflowModel#",
      "odrl": "http://www.w3.org/ns/odrl/",
      "foaf": "http://xmlns.com/foaf/0.1/",
      "org": "http://www.w3.org/ns/org#"
    },
    "@graph": [
      {
        "@id": "https://upcast-project.eu/consumer/example-data-consumer",
        "@type": [
          "foaf:Agent",
          "foaf:Organization",
          "org:Organization"
        ],
        "foaf:name": "Data Consumer Organization"
      },
      {
        "@id": "https://data-consumer.eu/agents/consumer-ai-agent",
        "@type": [
          "foaf:Agent",
          "http://data-space-vocabulary/classes/AI-Agent"
        ],
        "foaf:name": "Data Consumer AI Agent",
        "org:memberOf": {
          "@id": "https://upcast-project.eu/consumer/example-data-consumer"
        }
      },
      {
        "@id": "http://upcast-project.eu/dpws/example-dpw",
        "@type": "upcast:DataProcessingWorkflow",
        "wmo:wfPurposes": "Scientific Reseearch and Development",
        "wmo:Initiators": {
          "@id": "https://upcast-project.eu/consumer/example-data-consumer"
        },
        "wmo:includesTask": [
          {
            "@id": "http://upcast-project.eu/dpws/steps/step-1"
          },
          {
            "@id": "http://upcast-project.eu/dpws/steps/step-2"
          }
        ],
        "upcast:has_executable_representation": {
          "@id": "http://data-consumer.eu/my-nexflow-workflows/example-dpw-nexflow-script"
        }
      },
      {
        "@id": "http://upcast-project.eu/dpws/steps/step-1",
        "@type": "wmo:TaskNode",
        "wmo:hasExecutionProfile": {
          "@id": "http://upcast-project.eu/dpws/steps/profiles/execution-profile-1"
        }
      },
      {
        "@id": "http://upcast-project.eu/dpws/steps/profiles/execution-profile-1",
        "@type": "wmo:ExecutionProfile",
        "wmo:hasActor": {
          "@id": "https://upcast-project.eu/consumer/example-data-consumer"
        },
        "wmo:hasOperation": {
          "@id": "http://upcast-project.eu/dpws/steps/operations/operation-1"
        },
        "wmo:hasAsset": {
          "@id": "http://upcast-project.eu/dataset/example-dataset-agreed"
        }
      },
      {
        "@id": "http://upcast-project.eu/dpws/steps/operations/operation-1",
        "@type": "wmo:Operation",
        "wmo:refersToConcept": {
          "@id": "odrl:aggregate"
        },
        "upcast:implementedBy": {
          "@id": "http://upcast-project.eu/dpts/example-data-processing-task"
        }
      },
      {
        "@id": "http://upcast-project.eu/data-/example-data-processing-task",
        "@type": [
          "upcast:DataProcessingTask",
          "idsa-core:DataApp"
        ],
        "upcast:applies": {
          "@id": "odrl:aggregate"
        },
        "dct:title": "Example Data Processing Task",
        "dct:description": "Data Processing Task that implements an Abstract Operation of a DPW. In this case, odrl:aggregate"
      },
      {
        "@id": "http://upcast-project.eu/dpws/steps/step-2",
        "@type": "wmo:Operation",
        "wmo:hasExecutionProfile": {
          "@id": "http://upcast-project.eu/dpws/steps/profiles/execution-profile-2"
        }
      },
      {
        "@id": "http://upcast-project.eu/dpws/steps/profiles/execution-profile-2",
        "@type": "wmo:ExecutionProfile",
        "wmo:hasActor": {
          "@id": "https://data-consumer.eu/agents/consumer-ai-agent"
        },
        "wmo:hasOperation": {
          "@id": "http://upcast-project.eu/dpws/steps/operations/operation-2"
        },
        "wmo:hasAsset": {
          "@id": "http://upcast-project.eu/dataset/example-dataset-agreed"
        }
      },
      {
        "@id": "http://upcast-project.eu/dpws/steps/operations/operation-2",
        "@type": "wmo:Operation",
        "wmo:refersToConcept": {
          "@id": "odrl:translate"
        },
        "upcast:implementedBy": {
          "@id": "http://upcast-project.eu/dpts/AI-Agent-processor"
        }
      },
      {
        "@id": "http://upcast-project.eu/dpts/AI-Agent-processor",
        "@type": [
          "upcast:DataProcessingTask",
          "idsa-core:DataApp"
        ],
        "upcast:applies": {
          "@id": "odrl:translate"
        },
        "dct:title": "Example AI processor",
        "dct:description": "Data Processing Task done by AI-Agent"
      },
      {
        "@id": "http://upcast-project.eu/dpws/edges/edge-1",
        "@type": "wmo:Edge",
        "wmo:hasSource": {
          "@id": "http://upcast-project.eu/dpws/steps/step-1"
        },
        "wmo:hasDestination": {
          "@id": "http://upcast-project.eu/dpws/steps/step-2"
        }
      }
    ]
  }
}


def create_contract():
    endpoint_url = f"{BASE_URL}/contract/create"
    headers = {
        "user-id": "68821fc7eeea3fe76612e027",
        "Content-Type": "application/json",
    }

    # print("\n\ncreate_contract contract json data", json_data)

    try:
        response = requests.post(
            endpoint_url,
            json=json_data,
            headers=headers,
            timeout=30.0
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=502,
            detail=f"Error calling agreement API: {e}"
        )

    result = response.json()
    # inject generated natural language document
    json_data["natural_language_document"] = result.get('legal_contract')
    json_data["contract_id"] = result.get('contract_id')
    return json_data


def download_pdf(file_path, contract_id):

    url = f"{BASE_URL}/contract/download/{contract_id}"
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(f"{file_path}/contract-{contract_id}.pdf", "wb") as f:
            shutil.copyfileobj(r.raw, f)


def download_json(file_path, contract_id):
    url = f"{BASE_URL}/contract/download_mp/{contract_id}"
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(f"{file_path}/contract-{contract_id}.json", "wb") as f:
            shutil.copyfileobj(r.raw, f)

if __name__ == "__main__":

    # http://152.78.17.144:8006/contract/download_mp/68d11fc58cad15b8b8f0f7b9
    #

    # create_contract()

    path = "/home/mh1f25/scratch/upcast_pro/contract_service/negotiation-plugin/demo/"
    contract_id = "68d126108cad15b8b8f0f7ba"

    download_pdf(path, contract_id)
    # download_json(path, contract_id)