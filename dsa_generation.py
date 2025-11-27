import json
import re
from datetime import datetime
from num2words import num2words
from utils import create_odrl_decription, scrub_definitions
import re
from datetime import datetime, date

# new version 10 sep
def get_dsa_contract_text(data):
    """
    Build the Data Sharing Agreement text using the latest template:

    - PREAMBLE (explicit heading)
    - 1. SCOPE OF APPLICATION (1.1–1.4 as per template)
    - 2. DEFINITIONS (2.1, 2.2 fixed; 2.3 generated from `definitions`)
    - 3–12 as in template
    - 13. DURATION AND TERMINATION OF THE AGREEMENT (full clauses 13.1–13.4)
    - 14–17 as in template
    - 18. SIGNATURES (includes validity period sentence)
    - 19. Appendix (A1 ODRL + Data Resource + DPW [no hyphen]; A2 contacts)

    Notes
    -----
    - 4.2 references “Appendix A1”.
    - “The Parties must comply…” in Section 7.
    - GBP spelling and “£” prefix in 4.1 paragraph.
    """
    # -------------------------------
    # Local helpers
    # -------------------------------

    print("Call get_dsa_contract_text function ")

    def gv(d, k, default=""):
        return d.get(k, d.get(k.replace(" ", "_"), default))

    def norm_keys(d):
        return {str(k).lower().replace(" ", "_"): v for k, v in (d or {}).items()}

    def pick(d, *keys):
        for k in keys:
            if k in d and d[k] not in (None, ""):
                return d[k]
        return ""

    def coalesce(*vals):
        for v in vals:
            if isinstance(v, str) and v.strip():
                return v
            if v not in (None, "", {}):
                return v
        return ""

    def bullet(label, value):
        return f"\t\t• {label}: {value if (value or value == 0) else ''}"

    # def fmt_humandate(dt_str):
    #     """Return 'DD Month YYYY' where possible; preserve already-human strings; None if falsy."""
    #     if not dt_str:
    #         return None
    #     s = str(dt_str).strip()
    #     s = re.sub(r"\s+", "", s)
    #     fmts = [
    #         # "%Y-%m-%dT%H:%M:%S.%f%z",
    #         # "%Y-%m-%dT%H:%M:%S.%f",
    #         # "%Y-%m-%dT%H:%M:%S%z",
    #         # "%Y-%m-%dT%H:%M:%S",
    #         "%Y-%m-%d",
    #         "%d %B %Y",
    #         "%d %b %Y",
    #         "%d-%m-%Y",
    #     ]
    #     for f in fmts:
    #         try:
    #             dt = datetime.strptime(s, f)
    #             return dt.strftime("%d %B %Y")
    #         except Exception:
    #             pass
    #     return s



    def fmt_humandate(dt_str):
        """
        Normalize many date/datetime formats to 'YYYY-MM-DD'.
        - If input is datetime/date: use its date.
        - If string starts with YYYY-MM-DD (optionally followed by time), use that date.
        - Otherwise try a few human formats.
        - Return original string if parsing fails; None if input is falsy.
        """
        if not dt_str:
            return None

        if isinstance(dt_str, (datetime, date)):
            return dt_str.strftime("%Y-%m-%d")

        s = str(dt_str).strip()

        # 1) Handle anything that starts with 'YYYY-MM-DD' (with or without time)
        m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
        if m:
            try:
                dt = datetime.strptime(m.group(1), "%Y-%m-%d")
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass  # fall through to other formats

        # 2) Other common human-readable formats
        s_norm = re.sub(r"\s+", " ", s)

        fmts = [
            "%Y-%m-%d",
            "%d %B %Y",  # 20 November 2025
            "%d %b %Y",  # 20 Nov 2025
            "%d-%m-%Y",  # 20-11-2025
        ]

        for f in fmts:
            try:
                dt = datetime.strptime(s_norm, f)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        # 3) Give up, return original
        return s


    def human_today_london():
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Europe/London")
            today = datetime.now(tz).date()
        except Exception:
            today = datetime.now().date()
        return today.strftime("%d %B %Y")

    def render_party(section_title, party_dict):
        p = norm_keys(party_dict)
        lines = [f"\t\t{section_title}"]
        lines.append(bullet("Organization", pick(p, "organization", "org", "company_name", "name")))
        # keep legal rep if available (template sometimes omits it, but it’s useful)
        # if pick(p, "legal_representative", "representative", "rep_name"):
        #     lines.append(bullet("Legal Representative", pick(p, "legal_representative", "representative", "rep_name")))

        lines.append(bullet("Contact Person", pick(p, "name", "contact_name", "person")))
        lines.append(bullet("Position Title", pick(p, "position_title", "role", )))
        lines.append(bullet("Email", pick(p, "email", "e_mail", "username_email")))
        lines.append(bullet("Phone", pick(p, "phone", "telephone", "tel")))
        lines.append(bullet("Address", pick(p, "address", "registered_address", "postal_address")))
        notices_email = pick(p, "notices_email", "notice_email")
        notices_postal = pick(p, "notices_postal", "notice_address", "notices_address", "postal_address")
        preferred = pick(p, "preferred_method", "preferred_notice_method")
        if any([notices_email, notices_postal, preferred]):
            lines.append(bullet("Preferred Notice Method", preferred))
            lines.append(bullet("Email for Notices", notices_email))
            lines.append(bullet("Postal Address for Notices", notices_postal))
        lines.append("")
        return "\n".join(lines)

    def _description_41_natural(
            title, price, uri, policy_url, eco_gen, eco_srv,
            description, type_of_data, data_format, data_size, tags
    ):
        # Build a compact, natural-language paragraph matching the new template tone.
        bits = []
        if title or price:
            t = f'"{title}"' if title else "the dataset"
            price_txt = f" at a price of £{price}" if str(price).strip() else ""
            bits.append(f"The Data to be shared under this Agreement is the {t}{price_txt}.")
        if description:
            bits.append(f"{description}")
        if type_of_data or data_format or data_size:
            core = []
            if type_of_data: core.append(f"categorized as {type_of_data}")
            if data_format:  core.append(f"provided in {data_format.upper()}")
            if data_size:    core.append(f"has a total size of {data_size}")
            if core: bits.append("It is " + " and ".join(core) + ".")
        if uri or policy_url:
            access = []
            if uri: access.append(f"accessible at {uri}")
            if policy_url: access.append(f"with a policy available at {policy_url}")
            bits.append("It is " + (" and ".join(access) + "."))
        if tags:
            bits.append(f"Associated tags include {tags}.")
        if eco_gen or eco_srv:
            bits.append(
                "Environmental sustainability metrics for both generation and serving are detailed in Machine-Readable Appendix A1.")
        return "\n\t\t" + " ".join(bits) + "\n"

    # -------------------------------
    # Input unpacking / normalization
    # -------------------------------
    data_dict = data or {}
    policy_name_list = ["duty", "obligation", "permission", "prohibition"]

    client_optional_info = data_dict.get("client_optional_info", {}) or {}
    definitions = data_dict.get("definitions", {}) or {}
    policy_summary = data_dict.get("odrl_policy_summary", {}) or {}
    custom_clauses = data_dict.get("custom_clauses", {}) or {}
    # print ("custom_clauses", custom_clauses)
    odrl = data_dict.get("odrl", {}) or {}
    dpw_block = data_dict.get("dpw", {}) or {}
    resource_desc = norm_keys(data_dict.get("resource_description", {}))

    # if not policy_summary:
    #     synthesize from ODRL if absent
    # policy_summary = create_odrl_decription(odrl, definitions)

    policy_summary = create_odrl_decription(odrl, definitions)

    # definitions re-fine, remove following:
    # “personal data”, “data subject”, “processing”, “data controller”,
    # “data processor”, “third  party”, “consent”, “data breach”, “security incident”, “supervisory authority”,
    definitions = scrub_definitions(definitions)
    client_optional_info = norm_keys(client_optional_info)

    negotiation_id = gv(client_optional_info, "client_pid")
    print("negotiation_id: ", negotiation_id)
    updated_at = coalesce(gv(client_optional_info, "updated_at"))
    policy_id = coalesce(gv(client_optional_info, "policy_id"))
    contract_status = coalesce(gv(client_optional_info, "type"))

    title = coalesce(gv(resource_desc, "title"))
    price = coalesce(gv(resource_desc, "price"))
    uri = coalesce(gv(resource_desc, "uri"))
    policy_url = coalesce(gv(resource_desc, "policy_url"))
    eco_gen = coalesce(gv(resource_desc, "environmental_cost_of_generation"))
    eco_srv = coalesce(gv(resource_desc, "environmental_cost_of_serving"))
    description = coalesce(gv(resource_desc, "description"))
    type_of_data = coalesce(gv(resource_desc, "type_of_data"))
    data_format = coalesce(gv(resource_desc, "data_format"))
    data_size = coalesce(gv(resource_desc, "data_size"))
    tags = coalesce(gv(resource_desc, "tags"))

    contacts_block = data_dict.get("contacts", {})
    cp = norm_keys(contacts_block.get("provider", {}) or {})
    cc = norm_keys(contacts_block.get("consumer", {}) or {})

    effective_date_raw = data_dict.get("effective_date")
    effective_date = fmt_humandate(effective_date_raw) or fmt_humandate(updated_at) or human_today_london()

    provider_name = cp.get("organization")

    provider_title = coalesce(cp.get("type")).upper()

    provider_incorp = coalesce(cp.get("incorporation"), "…")
    provider_addr = coalesce(cp.get("registered_address"), cp.get("address"), "…")
    provider_vat = coalesce(cp.get("vat_no"), "…")

    provider_repr = coalesce(
        cp.get('name', '(please insert)')
    )
    provider_repr_role = coalesce(
        cp.get('position_title', '(please insert)')
    )

    consumer_name = coalesce(cc.get("organization"), "……")

    consumer_title = coalesce(cc.get("type")).upper()

    consumer_incorp = coalesce(cc.get("incorporation"), "…")
    consumer_addr = coalesce(cc.get("registered_address"), cc.get("address"), "…")
    consumer_vat = coalesce(cc.get("vat_no"), "…")

    consumer_repr = coalesce(
        cc.get('name', '(please insert)')
    )
    consumer_repr_role = coalesce(cc.get('position_title', ''), cc.get("position_title"), "…")

    validity_period = data_dict.get("validity_period")
    notice_period = data_dict.get("notice_period")

    if validity_period in (None, "", {}):
        term_text = "… months from the Effective Date, unless earlier terminated in accordance with this Agreement."
    else:
        # accept ints/strings
        try:
            months = int(validity_period)
            term_text = f"{months} months from the Effective Date, unless earlier terminated in accordance with this Agreement."
        except Exception:
            term_text = f"{validity_period} from the Effective Date, unless earlier terminated in accordance with this Agreement."

    # -------------------------------
    # Build document
    # -------------------------------
    ctx = []
    ctx.append("DATA SHARING AGREEMENT\n")

    # Table of Contents (matches the new template)
    toc = [
        "Table of Contents",
        "Preamble",
        "1. Scope of Application",
        "2. Definitions",
        "3. Purpose of the Agreement",
        "4. Description of Data",
        "5. Data Use – Permitted Purposes",
        "6. General Obligations of the Parties",
        "7. Policies and Rules",
        "8. Custom Arrangements",
        "9. Data Protection",
        "10. Technical and Organisational Security Measures – Data Sharing Mechanisms",
        "11. Confidentiality",
        "12. Liability",
        "13. Duration and Termination of the Agreement",
        "14. Contact",
        "15. Other Provisions",
        "16. Dispute Resolution",
        "17. Governing Law and Jurisdiction",
        "18. Signatures",
        "19. Appendix",
        "\tA1. Machine Readable",
        "\t\t1. ODRL Rules",
        "\t\t2. Data Resource Description",
        "\t\t3. Data Processing Workflow (DPW)",
        "\tA2. Communication and Persons in Charge",
        "",
    ]
    ctx.append("\n".join(toc))

    # PREAMBLE.
    preamble = f"""PREAMBLE.
This Data Sharing Agreement is made and entered into on {effective_date}, by and between the following contracting parties, namely:

(a) the company/organisation with the name “{provider_name}” and the distinctive title “{provider_title}”, incorporated in {provider_incorp}, and having its registered address at {provider_addr}, with VAT No. {provider_vat}, as legally represented at the time of signing of this Agreement by the {provider_repr_role}, {provider_repr}, hereinafter referred to, for the sake of brevity, as “Data Provider” or “Party A”; and

(b) the company/organisation with the name “{consumer_name}” and the distinctive title “{consumer_title}”, incorporated in {consumer_incorp}, and having its registered address at {consumer_addr}, with VAT No. {consumer_vat}, as legally represented at the time of signing of this Agreement by the {consumer_repr_role}, {consumer_repr}, hereinafter referred to, for the sake of brevity, as “Data Consumer” or “Party B”,

each hereinafter referred to as the “Party” and jointly both of the above the “Parties”, the following have been agreed and mutually accepted:
"""
    ctx.append(preamble.strip() + "\n")

    # 1. SCOPE OF APPLICATION.

    if negotiation_id:

        scope = f"""1. SCOPE OF APPLICATION.
        1.1. The Parties have entered into this Data Sharing Agreement to provide for the sharing of Data for the Permitted Purpose(s) (as defined below) and to ensure that there are appropriate provisions and arrangements in place to properly safeguard the information shared between the Parties. This Agreement and its Appendices (hereinafter the “Agreement”) set out the obligations of the Parties in relation to the sharing of data, including the obligations of the Parties’ employees or any sub-processors of data.
        1.2. The Parties seek to implement a data sharing agreement that complies with the requirements of the current data protection legal framework (e.g. the GDPR). Therefore, this Agreement shall also apply to any processing of personal data carried out pursuant to the current data protection legislation, on the basis of the contractual relationship between the Parties.
        1.3. This Agreement was generated using the UPCAST Negotiation Software (https://dips.soton.ac.uk/negotiation-plugin) under Negotiation ID {negotiation_id or "[insert ID]"}.
        1.4. This Agreement includes a human-readable section, which constitutes the legally binding contract between the Parties, and a corresponding Machine-Readable (MR) section, provided in the Appendix A1, to facilitate automated processing and enforcement.
        """
    else:
        scope = f"""1. SCOPE OF APPLICATION.
            1.1. The Parties have entered into this Data Sharing Agreement to provide for the sharing of Data for the Permitted Purpose(s) (as defined below) and to ensure that there are appropriate provisions and arrangements in place to properly safeguard the information shared between the Parties. This Agreement and its Appendices (hereinafter the “Agreement”) set out the obligations of the Parties in relation to the sharing of data, including the obligations of the Parties’ employees or any sub-processors of data.
            1.2. The Parties seek to implement a data sharing agreement that complies with the requirements of the current data protection legal framework (e.g. the GDPR). Therefore, this Agreement shall also apply to any processing of personal data carried out pursuant to the current data protection legislation, on the basis of the contractual relationship between the Parties.
            1.3. This Agreement includes a human-readable section, which constitutes the legally binding contract between the Parties, and a corresponding Machine-Readable (MR) section, provided in the Appendix A1, to facilitate automated processing and enforcement.
            """
    ctx.append(scope.strip() + "\n")

    # 2. DEFINITIONS.
    ctx.append("2. DEFINITIONS.")
    ctx.append(
        "2.1. For the purposes hereof, the terms “personal data”, “data subject”, “processing”, “data controller”, “data processor”, “third party”, “consent”, “data breach”, “security incident”, “supervisory authority”, as well as the other terms referred to herein shall have the same meaning as defined in the applicable legislation on personal data protection (including, but not limited to, General Regulation (EU) 2016/679 (“GDPR”) etc.).")
    ctx.append("2.2. The following terms shall have the meanings set out below:")
    ctx.append(
        "\t2.2.1. “Data Protection Legislation”: means (a) any law, statute, declaration, decree, directive, legislative enactment, order, ordinance, regulation, rule or other binding restriction (as amended, consolidated or re-enacted from time to time) which relates to the protection of individuals with regards to the processing of Personal Data to which a Party is subject, including but not limited to the GDPR, the UK General Data Protection Regulation (“UK GDPR”), and the Data Protection Act 2018 (“DPA”); and (b) any code of practice or guidance published by a Regulatory Body from time to time.")
    ctx.append(
        "\t2.2.2. “Pseudonymisation”: means the processing of personal data in such a manner that the personal data can no longer be attributed to a specific data subject without the use of additional information, provided that such additional information is kept separately and is subject to technical and organisational measures to ensure that the personal data are not attributed to an identified or identifiable natural person.")
    ctx.append(
        "\t2.3. The following terms used in the Agreement, and in the Machine-Readable (MR) section of the Appendix A1 shall have the meanings set out below:")
    if definitions:
        idx = 1
        for k, v in definitions.items():
            term = k.replace("_", " ").strip()
            meaning = (v or "").strip()
            ctx.append(f"\t\t2.3.{idx}. “{term}”: {meaning}")
            idx += 1
    else:
        ctx.append("\t\t(none)")
    ctx.append("")

    # 3. PURPOSE OF THE AGREEMENT.
    ctx.append("3. PURPOSE OF THE AGREEMENT.")
    ctx.append(
        f"The purpose of this Agreement is to define the terms and conditions governing the sharing of data between the Data Provider and the Data Consumer. Specifically, the Data Provider agrees to sell, and the Data Consumer agrees to purchase, the dataset titled “{title or '…'}” for a total consideration of {price or '…'} GBP.\n")

    # 4. DESCRIPTION OF DATA.
    ctx.append("4. DESCRIPTION OF DATA.")
    ctx.append("\t4.1. The Data to be shared under this Agreement is described as follows:")
    ctx.append(_description_41_natural(
        title, price, uri, policy_url, eco_gen, eco_srv,
        description, type_of_data, data_format, data_size, tags
    ))

    ctx.append(
        "\t4.2. The Machine-Readable (MR) version of the description of data (including its URI, description, format, size, associated tags, and environmental cost metrics) is presented in the Appendix A1.\n")

    # 5. DATA USE – PERMITTED PURPOSES.
    ctx.append("5. DATA USE – PERMITTED PURPOSES.")
    ctx.append(
        "\t5.1. The Shared Data shall be used by the Data Consumer solely for the permitted purpose(s) set out in Clauses 7 and 8.")
    ctx.append("\t5.2. No other use is permitted without prior written consent of the Data Provider.\n")

    # 6. GENERAL OBLIGATIONS OF THE PARTIES.
    ctx.append("6. GENERAL OBLIGATIONS OF THE PARTIES.")

    ctx.append(
        "\t6.1. Both Parties are obliged to fulfill their obligations hereunder, including the processing of the personal data processed, to comply with the applicable data protection law and to apply the basic principles for the protection of personal data, such as the principles of necessity, relevance, confidentiality, availability and integrity. The processing of personal data will also be carried out in accordance with the decisions of the competent Data Protection Authority, the working party under Article 29 of Directive 95/46/EC and the European Data Protection Board under Article 68 of the GDPR. ")
    ctx.append("\t6.2. The Data Provider shall ensure that the Data shared is accurate, complete, and up-to-date.")
    ctx.append(
        "\t6.3. The Data Consumer shall not transmit, disclose, tolerate or provide access to the Data to any third party without the prior written consent of the Data Provider, at its sole discretion, unless expressly required to do so under applicable law.\n")

    # 7. POLICIES AND RULES.
    ctx.append("7. POLICIES AND RULES.")
    ctx.append("The Parties must comply with the following Rules:")
    rule_index = 1
    custom_sections = []
    for section, policies in (policy_summary or {}).items():
        if section in policy_name_list:
            ctx.append(f"\t7.{rule_index}. {section.replace('_', ' ').title()}")
            if policies:
                for p in policies:
                    ctx.append(f"\t\t• {str(p).strip()}")
            else:
                ctx.append(f"\t\tThere are no {section} related rules.")
            ctx.append("")
            rule_index += 1
        else:
            lines = [f"\t8.{len(custom_sections) + 1}. {section.replace('_', ' ').title()}"]
            if policies:
                for p in policies:
                    for clause in (line.strip() for line in str(p).split("\n") if line.strip()):
                        lines.append(f"\t\t• {clause}")
            custom_sections.append("\n".join(lines))

    ctx.append(f"\t7.5. The Machine-Readable (MR) version of policies and rules is presented in the Appendix A1. \n")
    ctx.append("")
    # 8. CUSTOM ARRANGEMENTS.
    ctx.append("8. CUSTOM ARRANGEMENTS.")
    ctx.append(
        "In addition to the aforementioned (in Clause 7) standard policies, the following custom arrangements are mutually agreed upon by the Parties:")
    for ca_section, ca_policies in (custom_clauses or {}).items():
        lines = [f"\t8.{len(custom_sections) + 1}. {str(ca_section).replace('_', ' ').title()}"]
        if ca_policies:
            for p in ca_policies:
                for clause in (line.strip() for line in str(p).split("\n") if line.strip()):
                    lines.append(f"\t\t• {clause}")
        custom_sections.append("\n".join(lines))
    if custom_sections:
        ctx.append("\n".join(custom_sections))
    ctx.append("")

    # 9. DATA PROTECTION.
    ctx.append("9. DATA PROTECTION.")
    ctx.append(
        "\t9.1. The Parties may each process Personal Data under this Agreement. The Parties acknowledge that the factual arrangement between them dictates the classification of each Party in respect of the Data Protection Legislation. Notwithstanding the foregoing, the Parties anticipate that each Party shall act as a Controller in its own right. For the avoidance of doubt, the parties are not joint controllers for the purposes of Article 26 of the GDPR.")
    ctx.append(
        "\t9.2. Where a Party is acting as a Controller in relation to this Agreement, it shall comply with its obligations under the Data Protection Legislation.")
    ctx.append(
        "\t9.3. Where the Data Provider collects Personal Data which subsequently sells to the Data Consumer, Data Provider shall:")
    ctx.append(
        "\t\ti. Ensure that it is not subject to any prohibition or restriction which would prevent or restrict it from disclosing or transferring the Personal Data to the Data Consumer, as required under this Agreement; or prevent or restrict the Data Consumer from processing the Personal Data as envisaged under this Agreement;")
    ctx.append(
        "\t\tii. Ensure that all fair processing notices have been given (and/or, as applicable, valid consents obtained that have not been withdrawn) and are sufficient in scope and kept up-to-date in order to meet the transparency requirements to enable each Party to process the Personal Data in order to obtain the benefit of its rights, and to fulfil its obligations, under this Agreement in accordance with the Data Protection Legislation. For the avoidance of doubt, the Parties do not warrant to each other that any use of transferred Personal Data outside the scope of this Agreement shall be compliant with the Data Protection Legislation;")
    ctx.append(
        "\t\tiii. Ensure that the Personal Data is adequate, relevant and limited to what is necessary in relation to the Permitted Purpose; and accurate and, where necessary, up to date; having taken every reasonable step to ensure that any inaccurate Personal Data (having regard to the Permitted Purpose), has been erased or rectified; and")
    ctx.append("\t\tiv. Ensure that the Personal Data is transferred between the Parties by a secure means.")
    ctx.append(
        "\t9.4. Each Party shall indemnify and keep the other fully indemnified from and against any and all losses, fines, liabilities, damages, costs, claims, amounts paid in settlement and expenses (including legal fees, disbursements, costs of investigation, litigation, settlement, judgment, interest and penalties) that are sustained or suffered or incurred by, awarded against or agreed to be paid by, the other Party as a result of, or arising from, a breach by each Party of its obligations under this Clause 9 (Data Protection) and/or the Data Protection Legislation, including, in particular, pursuant to:")
    ctx.append("\t\ti. any monetary penalties or fines levied by any Regulatory Body on the other Party;")
    ctx.append(
        "\t\tii. the costs of any investigative, corrective or compensatory action required by any Regulatory Body, or of defending proposed or actual enforcement taken by any Regulatory Body;")
    ctx.append(
        "\t\tiii. any losses suffered or incurred by, awarded against, or agreed to be paid by the other Party, pursuant to a claim, action or challenge made by a third party against the other Party, (including by a data subject); and")
    ctx.append(
        "\t\tiv. except to the extent covered by Clause 12, any losses suffered or incurred, awarded against or agreed to be paid by the other Party.")
    ctx.append(
        "\t9.5. Nothing in this Agreement will exclude, limit or restrict each Party’s liability under the indemnity set out in Clause 12.\n")

    # 10. TECHNICAL AND ORGANISATIONAL SECURITY MEASURES - DATA SHARING MECHANISMS.
    ctx.append("10. TECHNICAL AND ORGANISATIONAL SECURITY MEASURES - DATA SHARING MECHANISMS.")
    ctx.append(
        "\t10.1. Both Parties shall implement and maintain, from the outset and before accessing the Data, appropriate technical and organisational measures, in accordance with current best practice and the state of the art in the relevant sector of activity, taking into account the implementation costs, and the nature, scope, circumstances and purpose of the processing, as well as the different probability of occurrence and the severity of the risk of the rights and freedoms of the persons concerned, in order to protect the Data being processed against accidental or unlawful destruction or accidental loss (including erasure), alteration (including destruction), modification, unauthorised disclosure, use or access and any other unlawful form of processing. Such measures will include, but shall not be limited to the pseudonymisation and encryption of Data, where appropriate; the ability to ensure the ongoing confidentiality, integrity, availability and resilience of processing systems and services on an ongoing basis; the ability to restore the availability and access to the Data in a timely manner in the event of a physical or technical incident, including a Data Breach; a process for regularly testing, assessing and evaluating the effectiveness of the technical and organisational measures in order to ensure the security of the processing of Data.")
    ctx.append(
        "\t10.2. In assessing the appropriate level of security, both Parties shall take account in particular of the risks that are presented by processing, in particular from a Personal Data Breach (as defined under GDPR).")
    ctx.append(
        "\t10.3. Both Parties agree to implement and maintain data-sharing mechanisms that: (a) comply with all applicable laws and regulations; (b) ensure the confidentiality and integrity of data during transmission; and (c) guarantee that each Party receives access to the Data as specified in this Agreement.")
    ctx.append(
        "\t10.4. Data sharing pursuant to this Agreement shall be conducted exclusively through secure communication channels.")
    ctx.append("\t10.5. All data transfers must be encrypted during transmission and comprehensively logged.\n")

    # 11. CONFIDENTIALITY.
    ctx.append("11. CONFIDENTIALITY.")
    ctx.append("\t11.1. Data Consumer agrees to treat all Data shared under this Agreement as confidential.")
    ctx.append(
        "\t11.2. Unless otherwise agreed, each Party shall maintain absolute confidentiality with respect to this Agreement, its activities and any information and documentation relating to the other Party (or anyone on its behalf) of which it becomes aware as a result of its cooperation with the other Party.")
    ctx.append(
        "\t11.3. The confidentiality and non-disclosure obligations set forth herein shall remain indefinitely, also following the termination and/or expiration of this Agreement and the cooperation of the Parties.\n")

    # 12. LIABILITY.
    ctx.append("12. LIABILITY.")
    ctx.append(
        "Each Party shall be fully liable to the other for any act and/or omission by itself and/or any of its employees, agents or assistants and/or any of its subcontractors. The defaulting Party is obliged to compensate its counterparty for any positive and/or consequential damage and/or moral damage that it or a third party (natural or legal person), to which the defaulting party is liable, may suffer from a breach of the obligations arising hereunder by it (i.e. the defaulting party), its employees, agents, assistants and/or any subcontractors.\n")

    # 13. DURATION AND TERMINATION OF THE AGREEMENT.
    ctx.append("13. DURATION AND TERMINATION OF THE AGREEMENT.")
    ctx.append(
        f"\t13.1. Either Party may terminate this Agreement for any significant reason by providing the other Party with {num2words(notice_period)} ({notice_period}) days’ prior written notice. For the purposes of this Agreement, a \"significant reason\" shall include, but is not limited to: (a) a change in applicable laws, regulations, or data protection requirements that makes data sharing unlawful or unduly burdensome; (b) reasonable concerns regarding the security, integrity, or misuse of shared data by the Data Consumer; (c) Reputational risk or public concern arising from the data sharing relationship; (d) a corporate transaction (such as a merger, acquisition, or divestiture) that materially affects the basis for this Agreement; and (e) a breakdown in the collaborative relationship that materially impairs the ability of the Parties to perform their obligations in good faith. The terminating Party shall act reasonably and in good faith when invoking a significant reason for termination.")
    ctx.append("\t13.2. A breach of any term hereof shall be deemed a material breach of this Agreement.")
    ctx.append("\t13.3. Upon termination of this Agreement for any reason:")
    ctx.append(
        "\t\t(a) Cessation of Data Sharing: Data Consumer shall immediately cease all operations related to the data being processed under this Agreement.")
    ctx.append(
        f"\t\t(b) Return or Destruction of Shared Data: Data Consumer shall, within {num2words(notice_period)} ({notice_period}) days of termination and in accordance with the instructions of the Data Provider, return or permanently and securely delete all data received from the Data Provider, unless retention is required to comply with applicable laws, regulations, or contractual obligations.")
    ctx.append(
        "\t\t(c) Confirmation of Destruction: Upon request, the Data Consumer shall provide written confirmation that all shared data has been destroyed in accordance with this clause.")
    ctx.append(
        "\t13.4. It is expressly agreed that the obligations assumed by the Parties under this Agreement shall survive the termination or any other cancellation of this Agreement.\n")

    # 14. CONTACT.
    ctx.append("14. CONTACT.")
    ctx.append(
        "\t14.1. With respect to any matter relating to this Agreement, the Parties shall communicate with each other through the contact persons, addresses, emails and telephone numbers listed in Appendix A2 of this Agreement.")
    ctx.append(
        "\t14.2. In the event of a change in the contact details, each Party shall inform the other Party in writing and without delay of the change.")
    ctx.append(
        "\t14.3. Any statement or notice sent between the Parties via email, as addressed, shall become effective upon receipt by the recipient. Any notice or communication sent by email shall be deemed received on the next business day following transmission (to the addresses indicated below), provided that no delivery failure notification is received by the sender.")
    ctx.append(
        "\t14.4. Notices made by post are deemed to have been delivered within seventy two (72) hours upon being sent, and if delivered by courier- on the date of the actual receipt signed by a representative of the recipient.\n")

    # 15. OTHER PROVISIONS.
    ctx.append("15. OTHER PROVISIONS.")
    ctx.append(
        "\t15.1. If any term of this Agreement is declared invalid or unenforceable for any reason or cause, the validity of this Agreement shall not be affected, and the remaining terms shall remain in effect as if the invalid or unenforceable term had not been included herein.")
    ctx.append("\t15.2. This Agreement may be amended only by new written agreement between the Parties.")
    ctx.append(
        "\t15.3. The Parties acknowledge that in the event of any conflict between the provisions of this Agreement and other prior agreements governing the processing of data, the provisions herein shall prevail.")
    ctx.append(
        "\t15.4. In the event of any inconsistency between the terms of this Agreement and the Appendices, the provisions of this Agreement shall prevail.\n")

    # 16. DISPUTE RESOLUTION.
    ctx.append("16. DISPUTE RESOLUTION.")
    ctx.append(
        "The Parties shall endeavour in good faith to resolve amicably any dispute and/or difference arising out of the Agreement and/or the Appendices thereto, which form an undivided and integral part thereof. In the event of failure to resolve any dispute / difference amicably, the courts of the country in which the Data Provider is located shall be exclusively responsible for its resolution.\n")

    # 17. GOVERNING LAW AND JURISDICTION.
    ctx.append("17. GOVERNING LAW AND JURISDICTION.")
    ctx.append(
        "\t17.1. This Agreement and any non-contractual obligations arising out of or in connection with it shall be governed by and interpreted in accordance with the laws of the country in which the Data Provider is located.")
    ctx.append(
        "\t17.2. Each Party irrevocably submits to the exclusive jurisdiction of the courts of the country in which the Data Provider is located over any claim or matter arising under, or in connection with, this Agreement.\n")

    # 18. SIGNATURES.
    sig = f"""18. SIGNATURES.
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

    # 19. Appendix
    ctx.append("19. Appendix")

    # A1. Machine Readable
    ctx.append("\tA1. Machine Readable")
    ctx.append("\t\t1. ODRL Rules\n")
    RULE_IRI = {
        "permission": "http://www.w3.org/ns/odrl/2/Permission",
        "prohibition": "http://www.w3.org/ns/odrl/2/Prohibition",
        "obligation": "http://www.w3.org/ns/odrl/2/Obligation",
        "duty": "http://www.w3.org/ns/odrl/2/Duty",
    }

    def _to_str(maybe_list):
        if isinstance(maybe_list, list):
            return ", ".join(map(str, maybe_list))
        return "" if maybe_list is None else str(maybe_list)

    def _flatten_constraints(items):
        """Flatten ODRL constraints supporting {'and':[...]} / {'or':[...]} groupings."""
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

    def _print_ref_block(ctx, label, value, indent_level=4):
        """
        Pretty-print 'action' / 'actor' / 'target' blocks.
        If 'value' is a string -> print single line.
        If 'value' is a dict with 'source'/'@type'/'refinement' -> print nested block like the example.
        Ill-formed refinement items (missing operator) are ignored.
        """
        base_indent = "\t" * indent_level
        sub_indent = "\t" * (indent_level + 1)

        # String-like (no refinements)
        if not isinstance(value, dict):
            ctx.append(f"{base_indent}{label}:   {_to_str(value)}")
            return

        # Dict-like (with potential refinements)
        ctx.append(f"{base_indent}{label}: ")
        if "@type" in value:
            ctx.append(f"{sub_indent} @type: '{_to_str(value.get('@type'))}', ")
        if "source" in value:
            ctx.append(f"{sub_indent} source: '{_to_str(value.get('source'))}', ")

        refs = value.get("refinement") or []
        # Only print "refinement" section if we have at least one well-formed triplet
        formatted_any = False
        lines = []
        for r in refs if isinstance(refs, list) else []:
            op = r.get("operator")
            left = _to_str(r.get("leftOperand", ""))
            right = _to_str(r.get("rightOperand", ""))
            if not op:  # ignore ill-formed refinements
                continue
            lines.append(f"{sub_indent}  - leftOperand: '{left}',")
            lines.append(f"{sub_indent}    operator: '{_to_str(op)}',")
            lines.append(f"{sub_indent}    rightOperand: '{right}'")
            formatted_any = True
        if formatted_any:
            ctx.append(f"{sub_indent} refinement: ")
            ctx.extend(lines)

    # --- Main block ---
    type_counter = 1
    for rule_type in ("permission", "prohibition", "obligation", "duty"):
        rules = data_dict.get("odrl", {}).get(rule_type, []) or odrl.get(rule_type, []) or []
        if not rules:
            continue

        ctx.append(f"\t\t\t{type_counter}. {rule_type.title()}:")
        for rule in rules:
            # Action / Actor / Target (can be string or dict-with-refinements)
            action_val = rule.get("action", "")
            actor_val = rule.get("actor") or rule.get("assignee") or rule.get("assigner") or ""
            target_val = rule.get("target", "")

            # Constraints (support nested groups) + purpose extraction
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
                if purpose_idx is None and flat_constraints:
                    first = flat_constraints[0]
                    purpose = _to_str(first.get("rightOperand", ""))
                    rest_constraints = flat_constraints[1:]
                else:
                    if purpose_idx is not None:
                        purpose = _to_str(flat_constraints[purpose_idx].get("rightOperand", ""))
                        rest_constraints = [c for j, c in enumerate(flat_constraints) if j != purpose_idx]

            # Print rule header
            ctx.append(f"\t\t\t\trule: {RULE_IRI.get(rule_type, rule_type)}")

            # Print action / actor / target blocks (with refinements if present)
            _print_ref_block(ctx, "action", action_val, indent_level=4)
            _print_ref_block(ctx, "actor", actor_val, indent_level=4)
            _print_ref_block(ctx, "target", target_val, indent_level=4)

            # Purpose (optional)
            if purpose:
                ctx.append(f"\t\t\t\tpurpose: '{purpose}'")

            # Remaining constraints (bulleted)
            if rest_constraints:
                ctx.append(f"\t\t\t\tconstraints:")
                for c in rest_constraints:
                    ctx.append(f"\t\t\t\t\t- leftOperand: {_to_str(c.get('leftOperand', ''))}")
                    ctx.append(f"\t\t\t\t\t  operator: {_to_str(c.get('operator', ''))}")
                    ctx.append(f"\t\t\t\t\t  rightOperand: {_to_str(c.get('rightOperand', ''))}\n")

            ctx.append("")  # blank line between rules

        type_counter += 1

    if type_counter == 1:
        ctx.append("\t\t\tNo ODRL rules are defined.\n")

    # for rule_type in ("permission", "prohibition", "obligation", "duty"):
    #     rules = data_dict.get("odrl", {}).get(rule_type, []) or odrl.get(rule_type, []) or []
    #
    #     print("odrl Rules", rules)
    #     if not rules:
    #         continue
    #     ctx.append(f"\t\t\t{type_counter}. {rule_type.title()}:")
    #     for rule in rules:
    #         action = _to_str(rule.get("action", ""))
    #         actor = rule.get("actor") or rule.get("assignee") or rule.get("assigner") or ""
    #         target = _to_str(rule.get("target", ""))
    #         all_constraints = rule.get("constraint", []) or rule.get("constraints", []) or []
    #         purpose = ""
    #         rest_constraints = []
    #         if all_constraints:
    #             purpose_idx = None
    #             for i, c in enumerate(all_constraints):
    #                 left = str(c.get("leftOperand", "")).lower()
    #                 tail = left.rsplit("/", 1)[-1]
    #                 if left == "purpose" or tail == "purpose" or left.endswith("purpose"):
    #                     purpose_idx = i
    #                     break
    #             if purpose_idx is None and all_constraints:
    #                 first = all_constraints[0]
    #                 purpose = _to_str(first.get("rightOperand", ""))
    #                 rest_constraints = all_constraints[1:]
    #             else:
    #                 if purpose_idx is not None:
    #                     purpose = _to_str(all_constraints[purpose_idx].get("rightOperand", ""))
    #                     rest_constraints = [c for j, c in enumerate(all_constraints) if j != purpose_idx]
    #         ctx.extend([
    #             f"\t\t\t\trule: {RULE_IRI.get(rule_type, rule_type)}",
    #             f"\t\t\t\taction:   {action}",
    #             f"\t\t\t\tactor: {actor}",
    #             f"\t\t\t\ttarget:   {target}",
    #         ])
    #         if purpose:
    #             ctx.append(f"\t\t\t\tpurpose: '{purpose}'")
    #         if rest_constraints:
    #             ctx.append(f"\t\t\t\tconstraints:")
    #             for c in rest_constraints:
    #                 ctx.append(f"\t\t\t\t\t- leftOperand: {_to_str(c.get('leftOperand', ''))}")
    #                 ctx.append(f"\t\t\t\t\t  operator: {_to_str(c.get('operator', ''))}")
    #                 ctx.append(f"\t\t\t\t\t  rightOperand: {_to_str(c.get('rightOperand', ''))}\n")
    #         ctx.append("")
    #     type_counter += 1
    # if type_counter == 1:
    #     ctx.append("\t\t\tNo ODRL rules are defined.\n")

    # 2) Data Resource Description
    ctx.append("\t\t2. Data Resource Description")
    if isinstance(data_dict.get("resource_description", {}), dict):
        for sub_key, sub_val in data_dict.get("resource_description", {}).items():
            if isinstance(sub_val, dict):
                non_empty = {k: v for k, v in sub_val.items() if v not in (None, "", [])}
                pretty = non_empty if non_empty else sub_val
                ctx.append(f"\t\t\t• {str(sub_key).replace('_', ' ').title()}: {pretty}")
            else:
                ctx.append(f"\t\t\t• {str(sub_key).replace('_', ' ').title()}: {sub_val}")
    ctx.append("")

    # 3) Data Processing Workflow (DPW)  (no hyphen, per template)
    ctx.append("\t\t3. Data Processing Workflow (DPW)")
    ctx.append("\t\t\t3.1. @context:")
    ctx_dict = dpw_block.get("@context", {}) or {}
    if ctx_dict:
        for prefix, iri in ctx_dict.items():
            ctx.append(f"\t\t\t\t{prefix}: {iri}")
    else:
        ctx.append("\t\t\t\t(none)")
    ctx.append("\n\t\t\t3.2. @graph:")
    graph = dpw_block.get("@graph", []) or []
    if graph:
        for idx, node in enumerate(graph, 1):
            nid = node.get("@id", "(no @id)")
            ntype = node.get("@type", "")
            if isinstance(ntype, list):
                ntype = ", ".join(ntype)
            ctx.append(f"\t\t\t\t• @id: {nid}")
            ctx.append(f"\t\t\t\t   @type: {ntype}")
            for k, v in node.items():
                if k in ("@id", "@type"):
                    continue
                if isinstance(v, dict):
                    val = v.get("@id", str(v))
                elif isinstance(v, list):
                    vals = []
                    for item in v:
                        vals.append(item.get("@id", str(item)) if isinstance(item, dict) else str(item))
                    val = ", ".join(vals)
                else:
                    val = str(v)
                ctx.append(f"\t\t\t\t   {k}: {val}")
            ctx.append("")
    else:
        ctx.append("\t\t\t\t(none)")

    # A2. Communication and Persons in Charge (add a blank line after title to ensure visible gap in PDF)
    ctx.append("\tA2. Communication and Persons in Charge\n")
    provider_contact = {}
    consumer_contact = {}
    # global_notices = {}

    if isinstance(contacts_block, dict):
        provider_contact = contacts_block.get("provider", {}) or contacts_block.get("data_provider", {}) or {}
        consumer_contact = contacts_block.get("consumer", {}) or contacts_block.get("data_consumer", {}) or {}
        # global_notices = contacts_block.get("notices", {}) or {}
    elif isinstance(contacts_block, list):
        for entry in contacts_block:
            e = norm_keys(entry)
            if e.get("party") in ("provider", "data_provider"):
                provider_contact = entry
            elif e.get("party") in ("consumer", "data_consumer"):
                consumer_contact = entry

    if provider_contact:
        ctx.append(render_party("A2.1 Data Provider", provider_contact))
    else:
        ctx.append("\t\tA2.1 Data Provider")
        ctx.append("\t\t\t(none)\n")

    if consumer_contact:
        ctx.append(render_party("A2.2 Data Consumer", consumer_contact))
    else:
        ctx.append("\t\tA2.2 Data Consumer")
        ctx.append("\t\t\t(none)\n")

    # if global_notices:
    #     gn = norm_keys(global_notices)
    #     ctx.append("\t\tA2.3 Notices (General)")
    #     ctx.append(bullet("Preferred Notice Method", pick(gn, "preferred_method", "preferred_notice_method")))
    #     ctx.append(bullet("Email for Notices", pick(gn, "email", "notices_email")))
    #     ctx.append(bullet("Postal Address for Notices", pick(gn, "postal_address", "address", "notices_postal")))
    #     ctx.append("")

    ctx.append("\n")

    print("End call get_dsa_contract_text function\n\n")
    return "\n".join(ctx)


def get_dsa_contract_json(data, *, include_text=False, include_predefined_texts: bool = True):
    """
    Build a machine-processable JSON for the DSA contract that aligns with your text generator.
    - Adds predefined 'text' fields for ALL sections 1..19 (Appendix includes A1/A2 blurbs).
    - Set include_predefined_texts=False to omit those pre-filled sentences.
    - Set include_text=True to embed the full human-readable contract text in the JSON.
    """

    # -------- helpers (mirror your text function) --------
    def gv(d, k, default=""):
        return (d or {}).get(k, (d or {}).get(k.replace(" ", "_"), default))

    def norm_keys(d):
        return {str(k).lower().replace(" ", "_"): v for k, v in (d or {}).items()}

    def pick(d, *keys):
        for k in keys:
            if k in d and d[k] not in (None, ""):
                return d[k]
        return ""

    def coalesce(*vals):
        for v in vals:
            if isinstance(v, str) and v.strip():
                return v
            if v not in (None, "", {}):
                return v
        return ""

    def _to_str(maybe_list):
        if isinstance(maybe_list, list):
            return ", ".join(map(str, maybe_list))
        return "" if maybe_list is None else str(maybe_list)

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

    def parse_iso_date(dt_str):
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
                return dt.date().isoformat()
            except Exception:
                pass
        return None

    def human_today_london():
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Europe/London")
            today = datetime.now(tz).date()
        except Exception:
            today = datetime.now().date()
        return today.strftime("%d %B %Y")

    def now_iso():
        try:
            return datetime.now().astimezone().isoformat()
        except Exception:
            return datetime.utcnow().isoformat() + "Z"

    def _flatten_constraints(items):
        """Flatten ODRL constraints supporting {'and':[...]} / {'or':[...]} groupings."""
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

    def _normalize_ref_value(value):
        """
        Normalize action / assignee / target into a consistent JSON shape:
          - if simple string, return {"value": "<str>"}
          - if dict with "@type"/"source"/"refinement", keep structured fields
            and turn refinements into a clean list of {leftOperand, operator, rightOperand}
        """
        if not isinstance(value, dict):
            return {"value": _to_str(value)}  # covers None/str/list

        out = {}
        if "@type" in value:
            out["@type"] = value.get("@type")
        if "source" in value:
            out["source"] = value.get("source")

        refs = value.get("refinement") or []
        clean_refs = []
        for r in refs if isinstance(refs, list) else []:
            op = r.get("operator")
            if not op:
                continue
            clean_refs.append({
                "leftOperand": _to_str(r.get("leftOperand", "")),
                "operator": _to_str(op),
                "rightOperand": _to_str(r.get("rightOperand", "")),
            })
        if clean_refs:
            out["refinement"] = clean_refs

        fallback_keys = [k for k in value.keys() if k not in {"@type", "source", "refinement"}]
        if not out and fallback_keys:
            return {"value": value}
        return out or {"value": ""}

    RULE_IRI = {
        "permission": "http://www.w3.org/ns/odrl/2/Permission",
        "prohibition": "http://www.w3.org/ns/odrl/2/Prohibition",
        "obligation": "http://www.w3.org/ns/odrl/2/Obligation",
        "duty": "http://www.w3.org/ns/odrl/2/Duty",
    }

    # -------- unpack inputs & normalize --------
    data_dict = data or {}
    client_optional_info = norm_keys(data_dict.get("client_optional_info", {}) or {})
    definitions = data_dict.get("definitions", {}) or {}
    policy_summary = data_dict.get("odrl_policy_summary", {}) or {}
    custom_clauses = data_dict.get("custom_clauses", {}) or {}
    odrl = data_dict.get("odrl", {}) or {}
    dpw_block = data_dict.get("dpw", {}) or {}
    resource_desc = norm_keys(data_dict.get("resource_description", {}))

    # Always compute policy_summary from ODRL + definitions (matches your text code)
    policy_summary = create_odrl_decription(odrl, definitions)
    definitions = scrub_definitions(definitions)

    contacts_block = data_dict.get("contacts", {}) or {}
    cp = norm_keys(contacts_block.get("provider", {}) or {})
    cc = norm_keys(contacts_block.get("consumer", {}) or {})

    negotiation_id = gv(client_optional_info, "client_pid")
    updated_at = coalesce(gv(client_optional_info, "updated_at"))
    policy_id = coalesce(gv(client_optional_info, "policy_id"))
    contract_status = coalesce(gv(client_optional_info, "type"))

    # print("\n\n\nclient_info:", negotiation_id, contract_status)


    title = coalesce(gv(resource_desc, "title"))
    price = coalesce(gv(resource_desc, "price"))
    uri = coalesce(gv(resource_desc, "uri"))
    policy_url = coalesce(gv(resource_desc, "policy_url"))
    eco_gen = coalesce(gv(resource_desc, "environmental_cost_of_generation"))
    eco_srv = coalesce(gv(resource_desc, "environmental_cost_of_serving"))
    description = coalesce(gv(resource_desc, "description"))
    type_of_data = coalesce(gv(resource_desc, "type_of_data"))
    data_format = coalesce(gv(resource_desc, "data_format"))
    data_size = coalesce(gv(resource_desc, "data_size"))
    tags = coalesce(gv(resource_desc, "tags"))

    effective_date_raw = data_dict.get("effective_date")
    effective_human = fmt_humandate(effective_date_raw) or fmt_humandate(updated_at) or human_today_london()
    effective_iso = parse_iso_date(effective_date_raw) or parse_iso_date(updated_at)

    provider = {
        "organization": coalesce(cp.get("organization")),
        "type": coalesce(cp.get("type")),
        "incorporation": coalesce(cp.get("incorporation")),
        "registered_address": coalesce(cp.get("registered_address"), cp.get("address")),
        "vat_no": coalesce(cp.get("vat_no")),
        "contact_person": coalesce(cp.get("name")),
        "position_title": coalesce(cp.get("position_title")),
        "email": coalesce(cp.get("email"), cp.get("username_email")),
        "phone": coalesce(cp.get("phone")),
        "address": coalesce(cp.get("address")),
        "notices": {
            "preferred_method": pick(cp, "preferred_method", "preferred_notice_method"),
            "email": pick(cp, "notices_email", "notice_email"),
            "postal": pick(cp, "notices_postal", "notice_address", "notices_address", "postal_address"),
        }
    }

    consumer = {
        "organization": coalesce(cc.get("organization")),
        "type": coalesce(cc.get("type")),
        "incorporation": coalesce(cc.get("incorporation")),
        "registered_address": coalesce(cc.get("registered_address"), cc.get("address")),
        "vat_no": coalesce(cc.get("vat_no")),
        "contact_person": coalesce(cc.get("name")),
        "position_title": coalesce(cc.get("position_title")),
        "email": coalesce(cc.get("email"), cc.get("username_email")),
        "phone": coalesce(cc.get("phone")),
        "address": coalesce(cc.get("address")),
        "notices": {
            "preferred_method": pick(cc, "preferred_method", "preferred_notice_method"),
            "email": pick(cc, "notices_email", "notice_email"),
            "postal": pick(cc, "notices_postal", "notice_address", "notices_address", "postal_address"),
        }
    }

    validity_period = data_dict.get("validity_period")
    notice_period = data_dict.get("notice_period")

    if validity_period in (None, "", {}):
        term_text = "… months from the Effective Date, unless earlier terminated in accordance with this Agreement."
        validity_months = None
    else:
        try:
            validity_months = int(validity_period)
            term_text = f"{validity_months} months from the Effective Date, unless earlier terminated in accordance with this Agreement."
        except Exception:
            validity_months = None
            term_text = f"{validity_period} from the Effective Date, unless earlier terminated in accordance with this Agreement."

    # -------- Build normalized ODRL A1 --------
    def build_odrl_rules():
        out = {}
        for rule_type in ("permission", "prohibition", "obligation", "duty"):
            rules = (data_dict.get("odrl", {}) or {}).get(rule_type, []) or odrl.get(rule_type, []) or []
            if not rules:
                continue
            bucket = []
            for rule in rules:
                # Normalize refs
                action_val = rule.get("action", "")
                # Prefer 'assignee'; do NOT emit 'assigner'
                assignee_val = rule.get("assignee") or rule.get("actor") or ""
                target_val = rule.get("target", "")

                action_norm = _normalize_ref_value(action_val)
                assignee_norm = _normalize_ref_value(assignee_val)
                target_norm = _normalize_ref_value(target_val)

                # Flatten constraints and extract (optional) purpose
                all_constraints_raw = rule.get("constraint", []) or rule.get("constraints", []) or []
                flat_constraints = _flatten_constraints(all_constraints_raw)

                purpose = None
                rest_constraints = []
                if flat_constraints:
                    purpose_idx = None
                    for i, c in enumerate(flat_constraints):
                        left = str(c.get("leftOperand", "")).lower()
                        tail = left.rsplit("/", 1)[-1]
                        if left == "purpose" or tail == "purpose" or left.endswith("purpose"):
                            purpose_idx = i
                            break
                    if purpose_idx is None:
                        rest_constraints = flat_constraints
                    else:
                        purpose = _to_str(flat_constraints[purpose_idx].get("rightOperand", ""))
                        rest_constraints = [c for j, c in enumerate(flat_constraints) if j != purpose_idx]

                bucket.append({
                    "type": RULE_IRI.get(rule_type, rule_type),
                    "action": action_norm,
                    "assignee": assignee_norm,
                    "target": target_norm,
                    **({"purpose": purpose} if purpose else {}),
                    **({"constraints": rest_constraints} if rest_constraints else {}),
                })
            if bucket:
                out[rule_type] = bucket
        return out

    odrl_a1 = build_odrl_rules()

    # -------- Predefined texts for all sections --------
    _title_for_text = title if title else "…"
    _price_for_text = str(price) if (price is not None and str(price).strip() != "") else "…"
    _neg_id_text = str(negotiation_id) if negotiation_id else "[insert ID]"
    _notice_days_text = str(notice_period) if notice_period is not None else "…"
    _notice_days_words = (num2words(notice_period) if isinstance(notice_period, int) else "…")

    text_1 = (
            "The Parties have entered into this Data Sharing Agreement to provide for the sharing of Data for the "
            "Permitted Purpose(s) and to ensure appropriate safeguards for information shared between the Parties. "
            "This Agreement applies to any processing of personal data carried out pursuant to applicable law. "
            + (
                f"This Agreement was generated via UPCAST Negotiation Software under Negotiation ID {_neg_id_text}. " if negotiation_id else "")
            + "It comprises a human-readable contract and a corresponding Machine-Readable (MR) section in Appendix A1."
    )

    text_2 = (
        "For the purposes of this Agreement, certain key terms shall have the meanings assigned by applicable "
        "data protection legislation (e.g., GDPR). Additional custom terms used herein and in the MR Appendix A1 "
        "are defined in this section."
    )

    text_3 = (
        "The purpose of this Agreement is to define the terms and conditions governing the sharing of data between "
        "the Data Provider and the Data Consumer. Specifically, the Data Provider agrees to sell, and the Data Consumer "
        f"agrees to purchase, the dataset titled {_title_for_text} for a total consideration of {_price_for_text} GBP.\n"
    )

    text_4 = (
        "This section summarises the Data being shared, including title, price, URI, format/size, tags, and any "
        "environmental metrics. A Machine-Readable version of this description is provided in Appendix A1."
    )

    text_5 = (
        "The Shared Data shall be used by the Data Consumer solely for the permitted purpose(s) set out in Clauses 7 and 8. "
        "No other use is permitted without prior written consent of the Data Provider."
    )

    text_6 = (
        "Both Parties must comply with applicable data protection law and implement appropriate measures (e.g., "
        "necessity, confidentiality, integrity, availability). The Data Provider shall ensure Data accuracy and currency. "
        "The Data Consumer shall not disclose or provide access to any third party without prior written consent, unless required by law."
    )

    text_7 = (
        "The Parties must comply with the policies and rules listed in this section (including ODRL-derived constraints "
        "and any custom policy groupings). A Machine-Readable version of policies and rules is provided in Appendix A1."
    )

    text_8 = (
        "In addition to the standard policies in Clause 7, the Parties agree to any specific custom arrangements codified here."
    )

    text_9 = (
        "Each Party may process Personal Data under this Agreement and shall comply with Data Protection Legislation. "
        "Where the Data Provider collects Personal Data that is sold to the Data Consumer, it must ensure lawful disclosure, "
        "adequate transparency/consents, data minimisation and accuracy, and secure transfer. Indemnities apply as specified herein."
    )

    text_10 = (
        "Both Parties shall implement and maintain appropriate technical and organisational security measures, taking into account "
        "the state of the art and risks. Data sharing must occur via secure channels, with encrypted transfers and comprehensive logging."
    )

    text_11 = (
        "The Data Consumer agrees to treat all Data as confidential. Unless otherwise agreed, each Party shall keep confidential this Agreement "
        "and any information relating to the other Party. Confidentiality obligations continue after termination."
    )

    text_12 = (
        "Each Party is fully liable to the other for acts/omissions of itself, its employees, agents, or subcontractors. "
        "The defaulting Party must compensate the other for damages caused by breaches of this Agreement."
    )

    text_13 = (
        f"Either Party may terminate this Agreement for a significant reason by providing {_notice_days_words} "
        f"({_notice_days_text}) days’ prior written notice. Upon termination, the Data Consumer shall cease processing and "
        "return or securely delete the Data (unless retention is legally required), and confirm destruction where requested. "
        "Certain obligations survive termination."
    )

    text_14 = (
        "Parties shall communicate using the contact persons and details listed in Appendix A2. Changes to contact details must be notified "
        "without delay. Email notices are effective upon receipt on the next business day (absent a delivery failure), and postal/courier "
        "notices are deemed delivered as specified in this Agreement."
    )

    text_15 = (
        "If any term is invalid or unenforceable, the remainder of the Agreement remains in force. Amendments require written agreement. "
        "In case of conflict with prior agreements, this Agreement prevails; in case of inconsistency with Appendices, this Agreement governs."
    )

    text_16 = (
        "The Parties shall seek to resolve disputes amicably. Failing that, the courts of the country in which the Data Provider is located "
        "have exclusive jurisdiction."
    )

    text_17 = (
        "This Agreement and any non-contractual obligations arising out of or in connection with it are governed by the laws of the country "
        "in which the Data Provider is located. Each Party submits to that jurisdiction."
    )

    text_18 = (
        f"This Agreement is entered into on the Effective Date and should remain in force for {term_text} "
        "Signature blocks for each Party appear in the human-readable contract; electronic records may be maintained."
    )

    text_19 = (
        "Appendix A1 (Machine Readable) contains the normalized ODRL rules, the data resource description, and the Data Processing Workflow (DPW). "
        "Appendix A2 contains contact details (communication and persons in charge) for both Parties."
    )

    # -------- Assemble final JSON --------
    contract_json = {
        "meta": {
            "generated_at": now_iso(),
            "generator": "UPCAST DSA JSON v1",
            "negotiation_id": negotiation_id or None,
            "policy_id": policy_id or None,
            "contract_status": contract_status or None,
            "effective_date": {
                "human": effective_human,
                "iso": effective_iso,
            },
        },
        "parties": {
            "provider": provider,
            "consumer": consumer,
        },
        "term": {
            "validity_period_months": validity_months,
            "term_text": term_text,
            "notice_period_days": notice_period,
            "notice_period_words": (num2words(notice_period) if isinstance(notice_period, int) else None)
        },
        "sections": {
            "1_scope_of_application": {
                "has_machine_readable_appendix": True,
                **({"text": text_1} if include_predefined_texts else {})
            },
            "2_definitions": {
                "fixed_terms_gdpr": [
                    "personal data", "data subject", "processing", "data controller",
                    "data processor", "third party", "consent", "data breach",
                    "security incident", "supervisory authority"
                ],
                "custom_terms": definitions,  # already scrubbed
                **({"text": text_2} if include_predefined_texts else {})
            },
            "3_purpose_of_the_agreement": {
                "dataset_title": title or None,
                "price_gbp": price or None,
                **({"text": text_3} if include_predefined_texts else {})
            },
            "4_description_of_data": {
                "title": title or None,
                "price_gbp": price or None,
                "uri": uri or None,
                "policy_url": policy_url or None,
                "description": description or None,
                "type_of_data": type_of_data or None,
                "data_format": data_format or None,
                "data_size": data_size or None,
                "tags": tags or None,
                "environment": {
                    "environmental_cost_of_generation": eco_gen or None,
                    "environmental_cost_of_serving": eco_srv or None
                },
                **({"text": text_4} if include_predefined_texts else {})
            },
            "5_data_use_permitted_purposes": {
                **({"text": text_5} if include_predefined_texts else {})
            },
            "6_general_obligations_of_the_parties": {
                **({"text": text_6} if include_predefined_texts else {})
            },
            "7_policies_and_rules": {
                **({"text": text_7} if include_predefined_texts else {})
            },
            "8_custom_arrangements": {
                **({"text": text_8} if include_predefined_texts else {})
            },
            "9_data_protection": {
                **({"text": text_9} if include_predefined_texts else {})
            },
            "10_technical_and_organisational_security_measures_data_sharing_mechanisms": {
                **({"text": text_10} if include_predefined_texts else {})
            },
            "11_confidentiality": {
                **({"text": text_11} if include_predefined_texts else {})
            },
            "12_liability": {
                **({"text": text_12} if include_predefined_texts else {})
            },
            "13_duration_and_termination_of_the_agreement": {
                **({"text": text_13} if include_predefined_texts else {})
            },
            "14_contact": {
                **({"text": text_14} if include_predefined_texts else {})
            },
            "15_other_provisions": {
                **({"text": text_15} if include_predefined_texts else {})
            },
            "16_dispute_resolution": {
                **({"text": text_16} if include_predefined_texts else {})
            },
            "17_governing_law_and_jurisdiction": {
                **({"text": text_17} if include_predefined_texts else {})
            },
            "18_signatures": {
                **({"text": text_18} if include_predefined_texts else {})
            },
            "19_appendix": {
                **({"text": text_19} if include_predefined_texts else {})
            },
        },
        "policies": {
            "odrl_policy_summary": policy_summary or {},
            "custom_clauses": custom_clauses or {}
        },
        "appendix": {
            "A1_machine_readable": {
                "odrl": odrl_a1,
                "resource_description": data_dict.get("resource_description", {}) or {},
                "dpw": dpw_block or {}
            },
            "A2_communication_and_persons_in_charge": {
                "provider": {
                    "organization": provider["organization"],
                    "contact_person": provider["contact_person"],
                    "position_title": provider["position_title"],
                    "email": provider["email"],
                    "phone": provider["phone"],
                    "address": provider["address"],
                    "notices": provider["notices"]
                },
                "consumer": {
                    "organization": consumer["organization"],
                    "contact_person": consumer["contact_person"],
                    "position_title": consumer["position_title"],
                    "email": consumer["email"],
                    "phone": consumer["phone"],
                    "address": consumer["address"],
                    "notices": consumer["notices"]
                }
            }
        }
    }

    if include_text:
        try:
            contract_json["contract_text"] = get_dsa_contract_text(data)
        except Exception:
            contract_json["contract_text"] = None

    return contract_json


def save_dsa_outputs(
        data,
        text_path: str = "dsa_contract.txt",
        json_path: str = "dsa_contract.json",
        *,
        include_text_inside_json: bool = True,
        json_indent: int = 2
):
    """
    Convenience writer: generates the human-readable text (using your existing function)
    AND the machine-readable JSON, then saves both to disk.
    Returns (text_path, json_path).
    """
    # Uses your existing function
    text = get_dsa_contract_text(data)
    obj = get_dsa_contract_json(data, include_text=include_text_inside_json)

    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=json_indent)

    return text_path, json_path
