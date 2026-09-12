"""FHIR R4 resource mappings for MediKiosk clinical data.
Maps internal models to FHIR R4 resources for ABDM exchange and interoperability."""
from datetime import datetime


class FHIRMapper:
    """Maps MediKiosk internal data to FHIR R4 resources."""

    @staticmethod
    def patient_to_fhir(patient: dict) -> dict:
        """Map PatientProfile to FHIR Patient resource."""
        fhir_patient = {
            "resourceType": "Patient",
            "id": str(patient.get("id", "")),
            "meta": {
                "profile": ["https://nrces.in/ndhm/fhir/r4/StructureDefinition/NDHM-Patient"]
            },
            "identifier": [],
            "name": [{
                "use": "official",
                "text": patient.get("full_name", "")
            }],
            "gender": patient.get("gender", "unknown"),
            "active": patient.get("is_active", True),
        }

        # Add ABHA as identifier
        if patient.get("abha_number"):
            fhir_patient["identifier"].append({
                "type": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                        "code": "MR",
                        "display": "Medical Record Number"
                    }]
                },
                "system": "https://abdm.gov.in/abha-number",
                "value": patient["abha_number"]
            })

        if patient.get("abha_address"):
            fhir_patient["identifier"].append({
                "type": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                        "code": "UDI",
                        "display": "Universal Device Identifier"
                    }]
                },
                "system": "https://abdm.gov.in/abha-address",
                "value": patient["abha_address"]
            })

        # Add phone
        if patient.get("phone"):
            fhir_patient["telecom"] = [{
                "system": "phone",
                "value": patient["phone"],
                "use": "mobile"
            }]

        # Add date of birth
        if patient.get("date_of_birth"):
            fhir_patient["birthDate"] = str(patient["date_of_birth"])

        return fhir_patient

    @staticmethod
    def encounter_to_fhir(encounter: dict) -> dict:
        """Map Encounter to FHIR Encounter resource."""
        status_map = {
            "intake": "triaged",
            "in_progress": "in-progress",
            "draft": "finished",
            "signed": "finished",
            "archived": "finished",
        }

        return {
            "resourceType": "Encounter",
            "id": str(encounter.get("id", "")),
            "meta": {
                "profile": ["https://nrces.in/ndhm/fhir/r4/StructureDefinition/NDHM-Encounter"]
            },
            "status": status_map.get(encounter.get("status", ""), "unknown"),
            "class": {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": "AMB",
                "display": "ambulatory"
            },
            "type": [{
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": "270427003",
                    "display": "Patient encounter"
                }]
            }],
            "subject": {
                "reference": f"Patient/{encounter.get('patient_id', '')}"
            },
            "period": {
                "start": encounter.get("started_at", datetime.utcnow()).isoformat() if encounter.get("started_at") else None
            }
        }

    @staticmethod
    def observation_to_fhir(observation: dict) -> dict:
        """Map clinical observation to FHIR Observation resource."""
        return {
            "resourceType": "Observation",
            "id": str(observation.get("id", "")),
            "status": "final",
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                    "code": "vital-signs",
                    "display": "Vital Signs"
                }]
            }],
            "code": {
                "coding": observation.get("code", []),
                "text": observation.get("display_name", "")
            },
            "valueQuantity": {
                "value": observation.get("value"),
                "unit": observation.get("unit", ""),
                "system": "http://unitsofmeasure.org"
            },
            "effectiveDateTime": observation.get("recorded_at"),
            "subject": {
                "reference": f"Patient/{observation.get('patient_id', '')}"
            },
            "encounter": {
                "reference": f"Encounter/{observation.get('encounter_id', '')}"
            }
        }

    @staticmethod
    def allergy_to_fhir(allergy: dict) -> dict:
        """Map allergy to FHIR AllergyIntolerance resource."""
        return {
            "resourceType": "AllergyIntolerance",
            "id": str(allergy.get("id", "")),
            "clinicalStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                    "code": allergy.get("status", "active")
                }]
            },
            "verificationStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                    "code": allergy.get("verification", "confirmed")
                }]
            },
            "type": allergy.get("type", "allergy"),
            "category": allergy.get("category", ["medication"]),
            "criticality": allergy.get("criticality", "low"),
            "code": {
                "coding": allergy.get("code", []),
                "text": allergy.get("substance", "")
            },
            "patient": {
                "reference": f"Patient/{allergy.get('patient_id', '')}"
            },
            "recordedDate": allergy.get("recorded_date")
        }

    @staticmethod
    def medication_to_fhir(medication: dict) -> dict:
        """Map medication to FHIR MedicationRequest resource."""
        return {
            "resourceType": "MedicationRequest",
            "id": str(medication.get("id", "")),
            "status": medication.get("status", "active"),
            "intent": "order",
            "medicationCodeableConcept": {
                "coding": medication.get("code", []),
                "text": medication.get("name", "")
            },
            "subject": {
                "reference": f"Patient/{medication.get('patient_id', '')}"
            },
            "encounter": {
                "reference": f"Encounter/{medication.get('encounter_id', '')}"
            },
            "authoredOn": medication.get("prescribed_date"),
            "requester": {
                "reference": f"Practitioner/{medication.get('prescriber_id', '')}"
            },
            "dosageInstruction": [{
                "text": medication.get("dosage_text", ""),
                "timing": {
                    "code": {
                        "text": medication.get("frequency", "")
                    }
                },
                "doseAndRate": [{
                    "doseQuantity": {
                        "value": medication.get("dose_value"),
                        "unit": medication.get("dose_unit", "")
                    }
                }]
            }]
        }

    @staticmethod
    def condition_to_fhir(condition: dict) -> dict:
        """Map condition/diagnosis to FHIR Condition resource."""
        return {
            "resourceType": "Condition",
            "id": str(condition.get("id", "")),
            "clinicalStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": condition.get("clinical_status", "active")
                }]
            },
            "verificationStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": condition.get("verification_status", "confirmed")
                }]
            },
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                    "code": "encounter-diagnosis",
                    "display": "Encounter Diagnosis"
                }]
            }],
            "code": {
                "coding": condition.get("code", []),
                "text": condition.get("description", "")
            },
            "subject": {
                "reference": f"Patient/{condition.get('patient_id', '')}"
            },
            "encounter": {
                "reference": f"Encounter/{condition.get('encounter_id', '')}"
            },
            "onsetDateTime": condition.get("onset_date")
        }

    @staticmethod
    def document_reference_to_fhir(doc: dict) -> dict:
        """Map document to FHIR DocumentReference resource."""
        return {
            "resourceType": "DocumentReference",
            "id": str(doc.get("id", "")),
            "status": doc.get("status", "current"),
            "type": {
                "coding": doc.get("type_code", []),
                "text": doc.get("type_display", "")
            },
            "subject": {
                "reference": f"Patient/{doc.get('patient_id', '')}"
            },
            "context": {
                "encounter": [{
                    "reference": f"Encounter/{doc.get('encounter_id', '')}"
                }]
            },
            "content": [{
                "attachment": {
                    "contentType": doc.get("content_type", "application/pdf"),
                    "url": doc.get("object_url", ""),
                    "size": doc.get("file_size", 0),
                    "title": doc.get("title", "")
                }
            }]
        }

    @staticmethod
    def clinical_summary_to_fhir_composition(summary: dict) -> dict:
        """Map ClinicalSummary to FHIR Composition resource."""
        return {
            "resourceType": "Composition",
            "id": str(summary.get("id", "")),
            "status": summary.get("status", "draft"),
            "type": {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": "11502-7",
                    "display": "Discharge summary"
                }]
            },
            "subject": {
                "reference": f"Patient/{summary.get('patient_id', '')}"
            },
            "encounter": {
                "reference": f"Encounter/{summary.get('encounter_id', '')}"
            },
            "date": summary.get("created_at", datetime.utcnow()).isoformat(),
            "author": [{
                "reference": f"Practitioner/{summary.get('signed_by', '')}"
            }],
            "title": f"Clinical Summary - {summary.get('summary_type', 'encounter')}",
            "section": [{
                "title": "Clinical Summary",
                "text": {
                    "status": "generated",
                    "div": f"<div xmlns='http://www.w3.org/1999/xhtml'>{summary.get('raw_text', '')}</div>"
                }
            }]
        }

    @staticmethod
    def create_bundle(entries: list[dict], bundle_type: str = "collection") -> dict:
        """Create a FHIR Bundle from multiple resources."""
        return {
            "resourceType": "Bundle",
            "type": bundle_type,
            "total": len(entries),
            "entry": [{
                "fullUrl": f"urn:uuid:{entry.get('id', '')}",
                "resource": entry
            } for entry in entries]
        }


# Singleton mapper
fhir_mapper = FHIRMapper()
