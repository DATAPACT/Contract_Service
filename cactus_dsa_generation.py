import re
from datetime import datetime
from typing import Any, Dict

from utils import create_odrl_decription, scrub_definitions, _money_eur


def get_cactus_dsa_contract_text(data: Dict[str, Any]) -> str:
    """
    CACTUS DSA – generator aligned with the latest user instructions:
    - TOC exactly as specified
    - Remove Definitions section and Data Protection section
    - Remove GDPR-like clause (old 1.2)
    - UPCAST clause is conditional: include only if Negotiation ID is available
    - Description of Data clause body reworded (no “The Data to be shared…” sentence)
    - Remove General Obligations 6.1 (old long principles clause)
    - TOMs 10.1: remove specific sentence fragment; remove 10.2 entirely
    """

    # ---------------- helpers ----------------
    def gv(d, k, default=""):
        d = d or {}
        return d.get(k, d.get(k.replace(" ", "_"), default))

    def norm_keys(d):
        return {str(k).lower().replace(" ", "_"): v for k, v in (d or {}).items()}

    def coalesce(*vals):
        for v in vals:
            if isinstance(v, str) and v.strip():
                return v.strip()
            if v not in (None, "", {}, []):
                return v
        return ""

    def fmt_humandate(dt_str):
        if not dt_str:
            return None
        s = str(dt_str).strip()
        s = re.sub(r"\s+", "", s)
        fmts = [
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
            "%d%B%Y",
            "%d%b%Y",
            "%d-%m-%Y",
        ]
        for f in fmts:
            try:
                dt = datetime.strptime(s, f)
                return dt.strftime("%d %B %Y")
            except Exception:
                pass
        return s

    def human_today_london():
        try:
            from zoneinfo import ZoneInfo
            today = datetime.now(ZoneInfo("Europe/London")).date()
        except Exception:
            today = datetime.now().date()
        return today.strftime("%d %B %Y")

    def _to_str(maybe_list):
        if isinstance(maybe_list, list):
            return ", ".join(map(str, maybe_list))
        return "" if maybe_list is None else str(maybe_list)



    def _desc_data_clause(
        type_of_data, data_format, data_size, uri, policy_url, tags, eco_gen, eco_srv
    ) -> str:
        """
        Matches requested wording style (no leading “The Data to be shared…” sentence,
        and no separate free-form description sentence).
        """
        # Categorization
        if isinstance(type_of_data, list):
            cat_txt = ", ".join(map(str, type_of_data))
        else:
            cat_txt = str(type_of_data).strip() if type_of_data else ""

        fmt_txt = str(data_format).strip() if data_format else "[]"
        size_txt = str(data_size).strip() if data_size else "[]"

        # Access phrase
        access_txt = "accessible via API" if uri else "accessible via []"

        # Policy phrase
        pol_txt = str(policy_url).strip() if policy_url else "[POLICY URL (policy id)]"

        # Tags phrase
        if isinstance(tags, list):
            tags_txt = ", ".join(map(str, tags))
        else:
            tags_txt = str(tags).strip() if tags else ""

        parts = []

        # Sentence 1
        if cat_txt and fmt_txt and size_txt:
            parts.append(
                f"It is categorized as {cat_txt}, and is provided in {fmt_txt} with a total size of {size_txt}.")
        else:
            parts.append(f"It is categorized as [please insert data-type], and is provided in [insert data format] with a total size of [insert data size].")

        parts.append(f"The dataset is {access_txt}, with usage governed by the policy available at {pol_txt}.")

        # Sentence 3
        if tags_txt:
            parts.append(f"Associated tags include {tags_txt}.")
        else:
            parts.append("Associated tags include [insert data tags/categories/key-words or themes].")

        # Sentence 4
        if eco_gen or eco_srv:
            parts.append("Environmental sustainability metrics for both generation and serving are detailed in Machine-Readable Appendix A1.")
        else:
            # keep the sentence (template-ish) but still consistent with your requested line
            parts.append("Environmental sustainability metrics for both generation and serving are detailed in Machine-Readable Appendix A1.")

        return "\t\t" + " ".join(parts) + "\n"

    def _pretty_block(obj, indent="\t\t\t"):
        if obj is None or obj == "":
            return f"{indent}(not provided)\n"
        if isinstance(obj, (str, int, float, bool)):
            return f"{indent}{obj}\n"
        if isinstance(obj, list):
            return "".join(_pretty_block(it, indent=indent) for it in obj)
        if isinstance(obj, dict):
            out = []
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    out.append(f"{indent}{k}:\n")
                    out.append(_pretty_block(v, indent=indent + "\t"))
                else:
                    out.append(f"{indent}{k}: {v}\n")
            return "".join(out)
        return f"{indent}{str(obj)}\n"

    def _has_real_id(x: Any) -> bool:
        s = str(x).strip() if x is not None else ""
        if not s:
            return False
        # treat common placeholders as "not available"
        placeholders = {"…", "...", "....", "…..", "—", "-", "_", "(please insert)", "[please insert]"}
        return s not in placeholders

    # ---------------- unpack inputs ----------------
    d = data or {}
    client_optional_info = norm_keys(d.get("client_optional_info", {}) or {})
    definitions = d.get("definitions", {}) or {}  # kept only for create_odrl_decription compatibility
    odrl = d.get("odrl", {}) or {}
    custom_clauses = d.get("custom_clauses", {}) or {}
    resource_desc = norm_keys(d.get("resource_description", {}))
    contacts = d.get("contacts", {}) or {}

    # Policy summary
    try:
        policy_summary = create_odrl_decription(odrl, definitions)
    except Exception:
        policy_summary = {}
    try:
        _ = scrub_definitions(definitions)  # we don't print definitions anymore, but keep scrub for downstream consistency
    except Exception:
        pass

    # Dates/meta
    updated_at = coalesce(gv(client_optional_info, "updated_at"))
    effective_date = fmt_humandate(d.get("effective_date")) or fmt_humandate(updated_at) or human_today_london()

    # Negotiation metadata (clause conditional)
    negotiation_id = coalesce(gv(client_optional_info, "client_pid"),
                              d.get("negotiation_id"))


    negotiation_software_url = "https://dips.soton.ac.uk/negotiation-plugin"

    # Contacts
    cp = norm_keys((contacts.get("provider") or {}) or {})
    cc = norm_keys((contacts.get("consumer") or {}) or {})

    provider_organization_name = coalesce(cp.get("organization"), cp.get("company_name"), "(please provide organization name)")
    provider_title = coalesce(cp.get("type"), "PROVIDER").upper()
    provider_incorp = coalesce(cp.get("incorporation"), "(please provide incorporation/country/region)")
    provider_addr = coalesce(cp.get("registered_address"), cp.get("address"), "(please provide address)")
    provider_vat = coalesce(cp.get("vat_no"), "(please provide vat number)")
    provider_repr = coalesce(cp.get("name"), "(please provide provider-repr name)")
    provider_repr_role = coalesce(cp.get("position_title"), cp.get("role"), "(please provide position title)")
    provider_email = coalesce(cp.get("email"), "(please provide email)")
    provider_phone = coalesce(cp.get("phone"), "(please provide phone)")

    consumer_organization_name = coalesce(cc.get("organization"), "(please provide organization name)")
    consumer_title = coalesce(cc.get("type"), "CONSUMER").upper()
    consumer_incorp = coalesce(cc.get("incorporation"), "(please provide incorporation/country/region)")
    consumer_addr = coalesce(cc.get("registered_address"), cc.get("address"), "(please provide address)")
    consumer_vat = coalesce(cc.get("vat_no"), "(please provide vat number)")
    consumer_repr = coalesce(cc.get("name"), "(please provide consumer-repr name)")
    consumer_repr_role = coalesce(cc.get("position_title"), "(please provide position title)")
    consumer_email = coalesce(cc.get("email"), "(please provide email)")
    consumer_phone = coalesce(cc.get("phone"), "(please provide phone)")

    # Resource
    title = coalesce(gv(resource_desc, "title"))
    price = coalesce(gv(resource_desc, "price"))
    uri = coalesce(gv(resource_desc, "uri"))
    policy_url = coalesce(gv(resource_desc, "policy_url"))
    eco_gen = coalesce(gv(resource_desc, "environmental_cost_of_generation"))
    eco_srv = coalesce(gv(resource_desc, "environmental_cost_of_serving"))
    type_of_data = coalesce(gv(resource_desc, "type_of_data"))
    data_format = coalesce(gv(resource_desc, "data_format"))
    data_size = coalesce(gv(resource_desc, "data_size"))
    tags = coalesce(gv(resource_desc, "tags"))


    categories = gv(resource_desc, "categories", "[please insert categories]")
    themes = gv(resource_desc, "themes")
    language = coalesce(gv(resource_desc, "language"))
    temporal_coverage = coalesce(gv(resource_desc, "temporal_coverage"))
    geographic_scope = coalesce(gv(resource_desc, "geographic_scope"))

    # Term months (signatures line)
    validity_period = d.get("validity_period")
    # if validity_period in (None, "", {}):
    #     term_months_txt = "[NUMBER OF MONTHS]"
    # else:
    #     try:
    #         term_months_txt = str(int(validity_period))
    #     except Exception:
    #         term_months_txt = str(validity_period)

    if validity_period in (None, "", {}):
        term_text = "(please provide term duration) months from the Effective Date, unless earlier terminated in accordance with this Agreement."
    else:
        # accept ints/strings
        try:
            months = int(validity_period)
            term_text = f"{months} months from the Effective Date, unless earlier terminated in accordance with this Agreement."
        except Exception:
            term_text = f"{validity_period} from the Effective Date, unless earlier terminated in accordance with this Agreement."


    # DPW
    dpw = coalesce(
        d.get("dpw"),
        d.get("data_processing_workflow"),
        d.get("dpw_jsonld"),
        d.get("workflow"),
        {},
    )

    # ---------------- build text ----------------
    ctx = []
    ctx.append("DATA SHARING AGREEMENT\n")

    # 1) TOC exactly as requested
    toc = [
        "Table of Contents",
        "Preamble",
        "1. Scope of Application",
        "2. Purpose of the Agreement",
        "3. Description of Data",
        "4. Data Use – Permitted Purposes",
        "5. General Obligations of the Parties",
        "6. Policies and Rules",
        "7. Custom Arrangements",
        "8. Technical and Organisational Security Measures – Data Sharing Mechanisms",
        "9. Confidentiality",
        "10. Liability",
        "11. Duration and Termination of the Agreement",
        "12. Contact",
        "13. Other Provisions",
        "14. Dispute Resolution",
        "15. Governing Law and Jurisdiction",
        "16. Signatures",
        "17. Appendix",
        "\tA1. Machine Readable",
        "\t\t1. ODRL Rules",
        "\t\t2. Data Resource Description",
        "\t\t3. Data-Processing Workflow (DPW)",
        "\tA2. Communication and Persons in Charge",
        "",
        "",
    ]
    ctx.append("\n".join(toc))

    preamble = f"""PREAMBLE.

This Data Sharing Agreement is made and entered into on {effective_date}, by and between the following contracting parties, namely:

(a) the company/organisation with the name “{provider_organization_name}” and the distinctive title “{provider_title}”, incorporated in {provider_incorp}, and having its registered address at {provider_addr}, with VAT No. {provider_vat}, as legally represented at the time of signing of this Agreement by the {provider_repr_role}, {provider_repr}, hereinafter referred to, for the sake of brevity, as “Data Provider” or “Party A”; and

(b) the company/organisation with the name “{consumer_organization_name}” and the distinctive title “{consumer_title}”, incorporated in {consumer_incorp}, and having its registered address at {consumer_addr}, with VAT No. {consumer_vat}, as legally represented at the time of signing of this Agreement by the {consumer_repr_role}, {consumer_repr}, hereinafter referred to, for the sake of brevity, as “Data Consumer” or “Party B”,

each hereinafter referred to as the “Party” and jointly both of the above the “Parties”, the following have been agreed and mutually accepted:
"""
    ctx.append(preamble.strip() + "\n")

    # 1. Scope of Application (remove old 1.2; make UPCAST clause conditional)
    ctx.append("1. SCOPE OF APPLICATION.\n")
    ctx.append(
        "1.1. The Parties have entered into this Data Sharing Agreement to provide for the sharing of Data for the "
        "Permitted Purpose(s) (as defined below) and to ensure that there are appropriate provisions and arrangements "
        "in place to properly safeguard the information shared between the Parties. This Agreement and its Appendices "
        "(hereinafter the “Agreement”) set out the obligations of the Parties in relation to the sharing of data, "
        "including the obligations of the Parties’ employees or any sub-processors of data.\n"
    )

    # Conditional UPCAST clause: include only if Negotiation ID is available
    if _has_real_id(negotiation_id):
        # Contract ID may be missing; still print placeholder if not real
        print ("negotiation is avaliable!")
        ctx.append(
            f"1.2. This Agreement was generated using the UPCAST Negotiation Software\n"
            f"({negotiation_software_url}) under Negotiation ID {negotiation_id}. \n"
        )
        ctx.append(
            "1.3. This Agreement includes a human-readable section, which constitutes the legally binding contract between the "
            "Parties, and a corresponding Machine-Readable (MR) section, provided in the Appendix A1, to facilitate automated "
            "processing and enforcement.\n"
        )
    else:
        # If 1.2 removed, keep MR statement as 1.2 (renumbered)
        ctx.append(
            "1.2. This Agreement includes a human-readable section, which constitutes the legally binding contract between the "
            "Parties, and a corresponding Machine-Readable (MR) section, provided in the Appendix A1, to facilitate automated "
            "processing and enforcement.\n"
        )

    # 2. Purpose (renumbered)
    ctx.append("2. PURPOSE OF THE AGREEMENT.\n")
    if str(price).strip() and int(str(price).strip()) !=0:
        ctx.append(
            "The purpose of this Agreement is to define the terms and conditions governing the sharing of data between the Data Provider "
            "and the Data Consumer. Specifically, the Data Provider agrees to sell, and the Data Consumer agrees to purchase, the dataset "
            f'titled “{title or "(please provide dataset title)"}” for a total consideration of {_money_eur(price)}.\n'
        )
    else:
        ctx.append(
            "The purpose of this Agreement is to define the terms and conditions governing the sharing of data between the Data Provider "
            "and the Data Consumer. Specifically, the Data Provider agrees to provide the Data Consumer with access to the data described below.\n"
        )

    # 3. Description of Data (requested 4.1-style content; no leading “The Data to be shared…” sentence)
    ctx.append("3. DESCRIPTION OF DATA.\n")
    ctx.append("3.1. The Data to be shared under this Agreement is described as follows:\n")
    ctx.append(_desc_data_clause(
        type_of_data=type_of_data,
        data_format=data_format,
        data_size=data_size,
        uri=uri,
        policy_url=policy_url,
        tags=tags,
        eco_gen=eco_gen,
        eco_srv=eco_srv,
    ))

    if geographic_scope and temporal_coverage:
        ctx.append(
            f"\t3.2. This data set contains the performance indicators of marketing campaigns in [{geographic_scope}] "
            f"concerning the {categories} business verticals within the defined time period {temporal_coverage}. "
            "The information provided at keyword level offer the possibility of generating detail description of the society interests and trends.\n")
        ctx.append("\t3.3. The Machine-Readable (MR) version of the description of data (including its URI, description, format, size, associated tags, "
                   "and environmental cost metrics) is presented in the Appendix A1.\n")

    else:
        ctx.append(
        "\t3.2. The Machine-Readable (MR) version of the description of data (including its URI, description, format, size, associated tags, "
        "and environmental cost metrics) is presented in the Appendix A1.\n")

    # 4. Data Use
    ctx.append("4. DATA USE – PERMITTED PURPOSES.\n")
    ctx.append("4.1. The Shared Data shall be used by the Data Consumer solely for the permitted purpose(s) set out in Clauses 6 and 7.\n")
    ctx.append("4.2. No other use is permitted without prior written consent of the Data Provider.\n")

    # 5. General Obligations (remove 5.1 long principles clause that was previously 6.1)
    ctx.append("5. GENERAL OBLIGATIONS OF THE PARTIES.\n")
    ctx.append("5.1. The Data Provider shall ensure that the Data shared is accurate, complete, and up-to-date.\n")
    ctx.append(
        "5.2. The Data Consumer shall not transmit, disclose, tolerate or provide access to the Data to any third party without the prior "
        "written consent of the Data Provider, at its sole discretion, unless expressly required to do so under applicable law.\n"
    )

    # 6. Policies and Rules
    ctx.append("6. POLICIES AND RULES.\n")
    ctx.append("The Parties must comply with the following Rules:\n")
    rule_index = 1
    for section, policies in (policy_summary or {}).items():
        ctx.append(f"6.{rule_index}. {str(section).replace('_', ' ').title()}\n")
        if policies:
            for p in policies:
                ctx.append(f"\t• {str(p).strip()}\n")
        else:
            ctx.append(f"\tThere are no {section} related rules.\n")
        ctx.append("")
        rule_index += 1
    ctx.append("6.5. The Machine-Readable (MR) version of policies and rules is presented in the Appendix A1.\n")

    # 7. Custom Arrangements
    ctx.append("7. CUSTOM ARRANGEMENTS.\n")
    ctx.append(
        "In addition to the aforementioned (in Clause 6) standard policies, the following custom arrangements are mutually agreed upon by the Parties:\n"
    )
    section_no = 1
    if custom_clauses:
        for ca_section, ca_policies in (custom_clauses or {}).items():
            ctx.append(f"\t7.{section_no} {str(ca_section).replace('_', ' ').title()}\n")
            if ca_policies:
                for p in ca_policies:
                    for clause in (line.strip() for line in str(p).split("\n") if line.strip()):
                        ctx.append(f"\t\t• {clause}\n")
            ctx.append("")
            section_no += 1
    else:
        ctx.append("\t7.1 (none)\n")

    # 8. TOMs (remove the specific sentence fragment; remove 8.2 entirely)
    ctx.append("8. TECHNICAL AND ORGANISATIONAL SECURITY MEASURES - DATA SHARING MECHANISMS.\n")
    ctx.append(
        "8.1. Both Parties shall implement and maintain, from the outset and before accessing the Data, appropriate technical and organisational measures, "
        "in accordance with current best practice and the state of the art in the relevant sector of activity, taking into account the implementation costs, "
        "and the nature, scope, circumstances and purpose of the processing, in order to protect the Data being processed against accidental or unlawful destruction "
        "or accidental loss (including erasure), alteration (including destruction), modification, unauthorised disclosure, use or access and any other unlawful form "
        "of processing. Such measures will include, but shall not be limited to the pseudonymisation and encryption of Data, where appropriate; the ability to ensure "
        "the ongoing confidentiality, integrity, availability and resilience of processing systems and services on an ongoing basis; the ability to restore the availability "
        "and access to the Data in a timely manner in the event of a physical or technical incident, including a Data Breach; a process for regularly testing, assessing "
        "and evaluating the effectiveness of the technical and organisational measures in order to ensure the security of the processing of Data.\n"
    )
    # 8.2 removed as requested
    ctx.append("8.2. Both Parties agree to implement and maintain data-sharing mechanisms that: (a) comply with all applicable laws and regulations; (b) ensure the confidentiality and integrity of data during transmission; and (c) guarantee that each Party receives access to the Data as specified in this Agreement.\n")
    ctx.append("8.3. Data sharing pursuant to this Agreement shall be conducted exclusively through secure communication channels.\n")
    ctx.append("8.4. All data transfers must be encrypted during transmission and comprehensively logged.\n")

    # 9. Confidentiality
    ctx.append("9. CONFIDENTIALITY.\n")
    ctx.append("9.1. Data Consumer agrees to treat all Data shared under this Agreement as confidential.\n")
    ctx.append("9.2. Unless otherwise agreed, each Party shall maintain absolute confidentiality with respect to this Agreement, its activities and any information and documentation relating to the other Party (or anyone on its behalf) of which it becomes aware as a result of its cooperation with the other Party.\n")
    ctx.append("9.3. The confidentiality and non-disclosure obligations set forth herein shall remain indefinitely, also following the termination and/or expiration of this Agreement and the cooperation of the Parties.\n")

    # 10. Liability
    ctx.append("10. LIABILITY.\n")
    ctx.append(
        "Each Party shall be fully liable to the other for any act and/or omission by itself and/or any of its employees, agents or assistants and/or any of its subcontractors. "
        "The defaulting Party is obliged to compensate its counterparty for any positive and/or consequential damage and/or moral damage that it or a third party (natural or legal person), "
        "to which the defaulting party is liable, may suffer from a breach of the obligations arising hereunder by it (i.e. the defaulting party), its employees, agents, assistants and/or any subcontractors.\n"
    )

    # 11. Duration & Termination
    ctx.append("11. DURATION AND TERMINATION OF THE AGREEMENT.\n")
    ctx.append(
        "11.1. Either Party may terminate this Agreement for any significant reason by providing the other Party with thirty (30) days’ prior written notice. "
        "For the purposes of this Agreement, a \"significant reason\" shall include, but is not limited to: (a) a change in applicable laws, regulations, or "
        "requirements that makes data sharing unlawful or unduly burdensome; (b) reasonable concerns regarding the security, integrity, or misuse of shared data by the Data Consumer; "
        "(c) reputational risk or public concern arising from the data sharing relationship; (d) a corporate transaction (such as a merger, acquisition, or divestiture) that materially "
        "affects the basis for this Agreement; and (e) a breakdown in the collaborative relationship that materially impairs the ability of the Parties to perform their obligations in good faith. "
        "The terminating Party shall act reasonably and in good faith when invoking a significant reason for termination.\n"
    )
    ctx.append("11.2. A breach of any term hereof shall be deemed a material breach of this Agreement.\n")
    ctx.append(
        "11.3. Upon termination of this Agreement for any reason:\n\n"
        "(a) Cessation of Data Sharing: Data Consumer shall immediately cease all operations related to the data being processed under this Agreement.\n\n"
        "(b) Return or Destruction of Shared Data: Data Consumer shall, within thirty (30) days of termination and in accordance with the instructions of the Data Provider, "
        "return or permanently and securely delete all data received from the Data Provider, unless retention is required to comply with applicable laws, regulations, or contractual obligations.\n\n"
        "(c) Confirmation of Destruction: Upon request, the Data Consumer shall provide written confirmation that all shared data has been destroyed in accordance with this clause.\n"
    )
    ctx.append("11.4. It is expressly agreed that the obligations assumed by the Parties under this Agreement shall survive the termination or any other cancellation of this Agreement.\n")

    # 12. Contact
    ctx.append("12. CONTACT.\n")
    ctx.append("12.1. With respect to any matter relating to this Agreement, the Parties shall communicate with each other through the contact persons, addresses, emails and telephone numbers listed in Appendix A2 of this Agreement.\n")
    ctx.append("12.2. In the event of a change in the contact details, each Party shall inform the other Party in writing and without delay of the change.\n")
    ctx.append("12.3. Any statement or notice sent between the Parties via email, as addressed, shall become effective upon receipt by the recipient. Any notice or communication sent by email shall be deemed received on the next business day following transmission (to the addresses indicated below), provided that no delivery failure notification is received by the sender.\n")
    ctx.append("12.4. Notices made by post are deemed to have been delivered within seventy two (72) hours upon being sent, and if delivered by courier- on the date of the actual receipt signed by a representative of the recipient.\n")

    # 13. Other Provisions
    ctx.append("13. OTHER PROVISIONS.\n")
    ctx.append("13.1. If any term of this Agreement is declared invalid or unenforceable for any reason or cause, the validity of this Agreement shall not be affected, and the remaining terms shall remain in effect as if the invalid or unenforceable term had not been included herein.\n")
    ctx.append("13.2. This Agreement may be amended only by new written agreement between the Parties.\n")
    ctx.append("13.3. The Parties acknowledge that in the event of any conflict between the provisions of this Agreement and other prior agreements governing the processing of data, the provisions herein shall prevail.\n")
    ctx.append("13.4. In the event of any inconsistency between the terms of this Agreement and the Appendices, the provisions of this Agreement shall prevail.\n")

    # 14. Dispute Resolution
    ctx.append("14. DISPUTE RESOLUTION.\n")
    ctx.append(
        "The Parties shall endeavour in good faith to resolve amicably any dispute and/or difference arising out of the Agreement and/or the Appendices thereto, "
        "which form an undivided and integral part thereof. In the event of failure to resolve any dispute / difference amicably, the courts of the country in which "
        "the Data Provider is located shall be exclusively responsible for its resolution.\n"
    )

    # 15. Governing Law & Jurisdiction
    ctx.append("15. GOVERNING LAW AND JURISDICTION.\n")
    ctx.append("15.1. This Agreement and any non-contractual obligations arising out of or in connection with it shall be governed by and interpreted in accordance with the laws of the country in which the Data Provider is located.\n")
    ctx.append("15.2. Each Party irrevocably submits to the exclusive jurisdiction of the courts of the country in which the Data Provider is located over any claim or matter arising under, or in connection with, this Agreement.\n")

    # 16. Signatures
    sig = f"""16. SIGNATURES.
    IN WITNESS WHEREOF, this Agreement has been entered into on the date stated at the beginning of it and should remain in force for {term_text}

    SIGNED by
    Duly authorised for and on behalf of “Data Provider”, {provider_repr}


                                                        Signature

                                                        ........................................
                                                        Name

                                                        ........................................
                                                        Date

                                                        ........................................


    SIGNED by
    Duly authorised for and on behalf of “Data Consumer”, {consumer_repr}


                                                        Signature

                                                        ........................................
                                                        Name

                                                        ........................................
                                                        Date

                                                        ........................................
    """
    ctx.append(sig.strip() + "\n")

    # 17. Appendix
    ctx.append("17. Appendix\n")
    ctx.append("\tA1. Machine Readable\n")
    ctx.append("\t\t1. ODRL Rules\n")

    RULE_IRI = {
        "permission": "http://www.w3.org/ns/odrl/2/Permission",
        "prohibition": "http://www.w3.org/ns/odrl/2/Prohibition",
        "obligation": "http://www.w3.org/ns/odrl/2/Obligation",
        "duty": "http://www.w3.org/ns/odrl/2/Duty",
    }

    def _flatten_constraints(items):
        flat = []
        if not items:
            return flat

        def _walk(obj):
            if isinstance(obj, dict):
                if {"leftOperand", "operator", "rightOperand"} <= obj.keys():
                    flat.append({
                        "leftOperand": obj.get("leftOperand"),
                        "operator": obj.get("operator"),
                        "rightOperand": obj.get("rightOperand"),
                    })
                else:
                    for k in ("and", "or"):
                        if k in obj and isinstance(obj[k], list):
                            for x in obj[k]:
                                _walk(x)
            elif isinstance(obj, list):
                for x in obj:
                    _walk(x)

        _walk(items)
        return flat

    def _print_ref_block(ctxp, label, value, indent_level=4):
        base_indent = "\t" * indent_level
        sub_indent = "\t" * (indent_level + 1)
        if not isinstance(value, dict):
            ctxp.append(f"{base_indent}{label}:   {_to_str(value)}\n")
            return
        ctxp.append(f"{base_indent}{label}:\n")
        if "@type" in value:
            ctxp.append(f"{sub_indent}@type: '{_to_str(value.get('@type'))}',\n")
        if "source" in value:
            ctxp.append(f"{sub_indent}source: '{_to_str(value.get('source'))}',\n")
        refs = value.get("refinement") or []
        lines = []
        for r in refs if isinstance(refs, list) else []:
            op = r.get("operator")
            left = _to_str(r.get("leftOperand", ""))
            right = _to_str(r.get("rightOperand", ""))
            if not op:
                continue
            lines.append(f"{sub_indent}- leftOperand: '{left}',\n")
            lines.append(f"{sub_indent}  operator: '{_to_str(op)}',\n")
            lines.append(f"{sub_indent}  rightOperand: '{right}'\n")
        if lines:
            ctxp.append(f"{sub_indent}refinement:\n")
            ctxp.extend(lines)

    # ODRL rules dump
    type_counter = 1
    for rule_type in ("permission", "prohibition", "obligation", "duty"):
        rules = (odrl or {}).get(rule_type, []) or []
        if not rules:
            continue
        ctx.append(f"\n\t\t\t{type_counter}. {rule_type.title()}:\n")
        for rule in rules:
            action_val = rule.get("action", "")
            actor_val = rule.get("actor") or rule.get("assignee") or rule.get("assigner") or ""
            target_val = rule.get("target", "")
            all_constraints_raw = rule.get("constraint", []) or rule.get("constraints", []) or []
            flat_constraints = _flatten_constraints(all_constraints_raw)

            purpose = ""
            rest_constraints = []
            if flat_constraints:
                purpose_idx = None
                for i, c in enumerate(flat_constraints):
                    left = str(c.get("leftOperand", "")).lower()
                    tail = left.rsplit("/", 1)[-1]
                    if left == "purpose" or tail == "purpose" or left.endswith("purpose"):
                        purpose_idx = i
                        break
                if purpose_idx is not None:
                    purpose = _to_str(flat_constraints[purpose_idx].get("rightOperand", ""))
                    rest_constraints = [c for j, c in enumerate(flat_constraints) if j != purpose_idx]
                else:
                    purpose = _to_str(flat_constraints[0].get("rightOperand", ""))
                    rest_constraints = flat_constraints[1:]

            ctx.append(f"\t\t\t\trule: {RULE_IRI.get(rule_type, rule_type)}\n")
            _print_ref_block(ctx, "action", action_val, indent_level=4)
            _print_ref_block(ctx, "actor", actor_val, indent_level=4)
            _print_ref_block(ctx, "target", target_val, indent_level=4)
            if purpose:
                ctx.append(f"\t\t\t\tpurpose: '{purpose}'\n")
            if rest_constraints:
                ctx.append(f"\t\t\t\tconstraints:\n")
                for cst in rest_constraints:
                    ctx.append(f"\t\t\t\t\t- leftOperand: {_to_str(cst.get('leftOperand', ''))}\n")
                    ctx.append(f"\t\t\t\t\t  operator: {_to_str(cst.get('operator', ''))}\n")
                    ctx.append(f"\t\t\t\t\t  rightOperand: {_to_str(cst.get('rightOperand', ''))}\n")
            ctx.append("\n")
        type_counter += 1

    if type_counter == 1:
        ctx.append("\t\t\tNo ODRL rules are defined.\n")

    # A1.2 Data Resource Description
    ctx.append("\t\t2. Data Resource Description\n\n")
    if isinstance(d.get("resource_description", {}), dict):
        for sub_key, sub_val in d.get("resource_description", {}).items():
            if isinstance(sub_val, dict):
                non_empty = {k: v for k, v in sub_val.items() if v not in (None, "", [])}
                pretty = non_empty if non_empty else sub_val
                ctx.append(f"\t\t\t• {str(sub_key).replace('_', ' ').title()}: {pretty}\n")
            else:
                ctx.append(f"\t\t\t• {str(sub_key).replace('_', ' ').title()}: {sub_val}\n")
    else:
        ctx.append("\t\t\t• (not provided)\n")

    # A1.3 DPW
    ctx.append("\n\t\t3. Data Processing Workflow (DPW)\n\n")
    if isinstance(dpw, dict) and ("@context" in dpw or "@graph" in dpw):
        ctx.append("\t\t\t3.1. @context:\n\n")
        ctx.append(_pretty_block(dpw.get("@context"), indent="\t\t\t\t"))
        ctx.append("\n\t\t\t3.2. @graph:\n\n")
        ctx.append(_pretty_block(dpw.get("@graph"), indent="\t\t\t\t"))
    else:
        ctx.append(_pretty_block(dpw, indent="\t\t\t"))

    # A2 contacts
    ctx.append("\n\tA2. Communication and Persons in Charge\n\n")
    ctx.append("\t\tA2.1 Data Provider\n")
    ctx.append(f"\t\t\t• Organization: {provider_organization_name}\n")
    ctx.append(f"\t\t\t• Contact Person: {provider_repr}\n")
    ctx.append(f"\t\t\t• Role/Title: {provider_repr_role}\n")
    ctx.append(f"\t\t\t• Email: {provider_email}\n")
    ctx.append(f"\t\t\t• Phone: {provider_phone}\n")
    ctx.append(f"\t\t\t• Address: {provider_addr}\n\n")

    ctx.append("\t\tA2.2 Data Consumer\n")
    ctx.append(f"\t\t\t• Organization: {consumer_organization_name}\n")
    ctx.append(f"\t\t\t• Contact Person: {consumer_repr}\n")
    ctx.append(f"\t\t\t• Role/Title: {consumer_repr_role}\n")
    ctx.append(f"\t\t\t• Email: {consumer_email}\n")
    ctx.append(f"\t\t\t• Phone: {consumer_phone}\n")
    ctx.append(f"\t\t\t• Address: {consumer_addr}\n")

    return "\n".join(ctx)
