import re
from datetime import datetime
import re
from datetime import datetime, date

from sympy.integrals.meijerint_doc import category

from utils import create_odrl_decription, scrub_definitions, _money_eur


# version 1,  11-09-2025
def get_consent_contract_text(data):
    """
    DATA CONSENT AGREEMENT generator (MI_2025.09.11).

    Matches the updated template structure:
      TOC: Preamble → 1..17 (Signatures) → 18. Appendix
        A1: (1) ODRL Rules, (2) Data Resource Description
        A2: Communication and Persons in Charge
    Notes:
      - Section 4 uses "processed" (not "shared").
      - §5.1 references Clauses 7 and 8.
      - §7 shows Permission only (no Prohibition/Obligation/Duty in the body).
      - Appendix A1 omits DPW.
    """

    print("Call get_consent_contract_text function ")

    # ------------------------------- helpers -------------------------------
    def gv(d, k, default=""):
        d = d or {}
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

    def as_list(x):
        if x is None or x == "":
            return []
        if isinstance(x, list):
            return x
        return [x]

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
            today = datetime.now(ZoneInfo("Europe/London")).date()
        except Exception:
            today = datetime.now().date()
        return today.strftime("%d %B %Y")

    def bullet(label, value):
        return f"\t\t• {label}: {value if (value or value == 0) else ''}"

    # A2 blocks
    def render_provider_individual(p):
        p = norm_keys(p)
        lines = ["\t\tA2.1 Data Provider"]
        lines.append(bullet("Full name", pick(p, "full_name", "name")))
        lines.append(bullet("Email", pick(p, "username_email", "user_email")))
        lines.append(bullet("Phone", pick(p, "phone", "telephone", "tel")))
        lines.append(bullet("Address", pick(p, "address", "residential_address", "registered_address")))
        lines.append("")
        return "\n".join(lines)

    def render_consumer_org(c):
        c = norm_keys(c)
        lines = ["\t\tA2.2 Data Consumer"]
        lines.append(bullet("Organization", pick(c, "organization", "company_name", "name")))
        lines.append(bullet("Contact Person", pick(c, "contact_person", "contact_name", "name")))
        lines.append(bullet("Role/Title", pick(c, "position_title", "role", "title", "position")))
        lines.append(bullet("Email", pick(c, "username_email", "user_email")))
        lines.append(bullet("Phone", pick(c, "phone", "telephone", "tel")))
        lines.append(bullet("Address", pick(c, "address", "registered_address", "postal_address")))
        lines.append("")
        return "\n".join(lines)

    def _description_41_natural(
            title, price, uri, policy_url, eco_gen, eco_srv,
            description, type_of_data, data_format, data_size, tags
    ):
        # Compact paragraph; "processed" + £ for price
        bits = []
        if title or price:
            t = f'"{title}"' if title else "the data"
            price_txt = f" at a price of €{0.00}" if str(price).strip() else ""
            # price_txt = f" at a price of £{price}" if str(price).strip() else ""
            bits.append(f'The Data to be processed under this Agreement is {t}{price_txt}.')
        if description:
            bits.append(str(description))
        if type_of_data or data_format or data_size:
            core = []
            if type_of_data: core.append(f"categorized as {type_of_data}")
            if data_format:  core.append(f"provided in {data_format}")
            if data_size:    core.append(f"total size {data_size}")
            if core: bits.append("It is " + " and ".join(core) + ".")
        if uri or policy_url:
            access = []
            if uri: access.append(f"accessible at {uri}")
            if policy_url: access.append(f"with usage governed by the policy available at {policy_url}")
            bits.append("It is " + (" and ".join(access) + "."))
        if tags:
            tags_txt = ", ".join(map(str, tags)) if isinstance(tags, list) else str(tags)
            bits.append(f"Associated tags include {tags_txt}.")
        if eco_gen or eco_srv:
            bits.append(
                "Environmental sustainability metrics for both generation and serving are detailed in Machine-Readable Appendix A1.")
        return "\n\t\t" + " ".join(bits) + "\n"

    def _to_str(maybe_list):
        if isinstance(maybe_list, list):
            return ", ".join(map(str, maybe_list))
        return "" if maybe_list is None else str(maybe_list)

    # --------------------------- unpack / normalize ---------------------------
    d = data or {}
    client_optional_info = norm_keys(d.get("client_optional_info", {}) or {})
    definitions = d.get("definitions", {}) or {}
    custom_definitions = d.get("custom_definitions") or {}
    definitions.update(custom_definitions)
    # policy_summary  = d.get("odrl_policy_summary", {}) or {}
    odrl = d.get("odrl", {}) or {}
    custom_clauses = d.get("custom_clauses", {}) or {}
    if not isinstance(custom_clauses, dict):
        custom_clauses = {}
    resource_desc = norm_keys(d.get("resource_description", {}))
    contacts = d.get("contacts", {}) or {}

    policy_summary = {}
    # Synthesize ODRL summary if available in your codebase
    try:
        ps = create_odrl_decription(odrl, definitions)
        if isinstance(ps, dict):
            policy_summary = ps
    except Exception:
        pass

    # Permission-only in Section 7
    permissions = as_list(policy_summary.get("permission", [])) if isinstance(policy_summary, dict) else []

    # Definitions scrub (if helper exists)
    try:
        definitions = scrub_definitions(definitions)
    except Exception:
        pass

    # Dates
    consent_id = gv(client_optional_info, "client_pid")
    print("consent_id: ", consent_id)
    policy_id = coalesce(gv(client_optional_info, "policy_id"))
    contract_status = coalesce(gv(client_optional_info, "type"))
    updated_at = coalesce(gv(client_optional_info, "updated_at"))

    effective = fmt_humandate(d.get("effective_date")) or fmt_humandate(updated_at) or human_today_london()

    # Resource fields
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
    tags = gv(resource_desc, "tags", "")
    categories = gv(resource_desc, "categories", "[please insert categories]")
    themes = gv(resource_desc, "themes")


    language = coalesce(gv(resource_desc, "language"))
    temporal_coverage = coalesce(gv(resource_desc, "temporal_coverage"))
    geographic_scope = coalesce(gv(resource_desc, "geographic_scope"))


    # Contacts (provider is individual; consumer is org)
    cp = norm_keys(contacts.get("provider", {}) or contacts.get("data_provider", {}) or {})
    cc = norm_keys(contacts.get("consumer", {}) or contacts.get("data_consumer", {}) or {})

    provider_fullname = coalesce(cp.get("full_name"), cp.get("name"), "(please provide full name)")
    provider_citizen = coalesce(cp.get(""
                                       ""), cp.get("citizen"), "(please provide citizenship)")

    provider_pid = coalesce(cp.get("passport_id"), cp.get("passport_no"), cp.get("id_no"), "(please provide passport/ID number)")
    provider_addr = coalesce(cp.get("address"), cp.get("registered_address"), "(please provide address)")

    consumer_org = coalesce(cc.get("organization"), cc.get("company_name"), cc.get("name"), "(please provide organization name)")
    consumer_title = coalesce(cc.get("type"), cc.get("distinctive_title")).upper()
    consumer_incorp = coalesce(cc.get("incorporation"), cc.get("country"), "(please provide place of incorporation)")
    consumer_addr = coalesce(cc.get("address"), "(please provide address)")
    consumer_vat = coalesce(cc.get("vat_no"), "(please provide vat number)")
    consumer_rep = coalesce(cc.get("name"), "(please provide representative name)")
    consumer_rep_role = coalesce(cc.get("position_title"), cc.get("role"), cc.get("position"), "(please provide representative role)")

    # Consent revocation / rights email: prefer a dedicated field, else consumer notices
    rights_email = coalesce(
        cc.get("email"),
        "…"
    )

    # Signature term text
    validity_period = d.get("validity_period")
    if validity_period in (None, "", {}):
        term_text = "(please provide term duration) months from the Effective Date, unless earlier terminated in accordance with this Agreement."
    else:
        try:
            months = int(validity_period)
            term_text = f"{months} months from the Effective Date, unless earlier terminated in accordance with this Agreement."
        except Exception:
            term_text = f"{validity_period} from the Effective Date, unless earlier terminated in accordance with this Agreement."

    # ------------------------------- build doc -------------------------------
    ctx = []
    ctx.append("DATA CONSENT AGREEMENT\n")

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
        "10. Technical and Organisational Security Measures - Data Sharing Mechanisms",
        "11. Confidentiality",
        "12. Liability",
        "13. Contact",
        "14. Other Provisions",
        "15. Dispute Resolution",
        "16. Governing Law and Jurisdiction",
        "17. Signatures",
        "18. Appendix",
        "\tA1. Machine Readable",
        "\t\t1. ODRL Rules",
        "\t\t2. Data Resource Description",
        "\tA2. Communication and Persons in Charge",
        "",
    ]
    ctx.append("\n".join(toc))

    # PREAMBLE (individual provider + org consumer)
    preamble = f"""PREAMBLE.
This Data Consent Agreement is made and entered into on {effective}, by and between the following contracting parties, namely:

(a) {provider_fullname}, a {provider_citizen} citizen, holder of passport/ID no. {provider_pid}, residing at {provider_addr}, hereinafter referred to, for the sake of brevity, as “Data Provider” or “Data subject” or “Party A”; and

(b) the company/organisation with the name “{consumer_org}” and the distinctive title “{consumer_title}”, incorporated in {consumer_incorp}, and having its registered address at {consumer_addr}, with VAT No. {consumer_vat}, as legally represented at the time of signing of this Agreement by the {consumer_rep}, {consumer_rep_role}, hereinafter referred to, for the sake of brevity, as “Data Consumer” or “Data controller” or “Party B”,

each hereinafter referred to as the “Party” and jointly both of the above the “Parties”, the following have been agreed and mutually accepted:
"""
    ctx.append(preamble.strip() + "\n")

    # 1. SCOPE OF APPLICATION
    if consent_id:

        scope = f"""1. SCOPE OF APPLICATION.
        \t1.1. The Parties have entered into this Data Consent Agreement to provide for the sharing and processing of Data for the Permitted Purpose(s) (as defined below) and to ensure that there are appropriate provisions and arrangements in place to properly safeguard the information shared between the Parties. This Agreement and its Appendices (hereinafter the “Agreement”) set out the obligations of the Parties in relation to the processing of data, including the obligations of the Data Consumer’s employees or any sub-processors of data.
        \t1.2. The Parties seek to implement a data consent agreement that complies with the requirements of the current data protection legal framework (e.g. the GDPR). Therefore, this Agreement shall apply to any processing of personal data carried out pursuant to the current data protection legislation.
        \t1.3. This Agreement was generated using the UPCAST Contract Service(https://dips.soton.ac.uk/contract-service-api/docs) 
        under Consent ID {consent_id}.
        \t1.4. This Agreement includes a human-readable section, which constitutes the legally binding contract between the Parties, and a corresponding Machine-Readable (MR) section, provided in the Appendix A1, to facilitate automated processing and enforcement.
        """

    else:
        scope = """1. SCOPE OF APPLICATION.
        \t1.1. The Parties have entered into this Data Consent Agreement to provide for the sharing and processing of Data for the Permitted Purpose(s) (as defined below) and to ensure that there are appropriate provisions and arrangements in place to properly safeguard the information shared between the Parties. This Agreement and its Appendices (hereinafter the “Agreement”) set out the obligations of the Parties in relation to the processing of data, including the obligations of the Data Consumer’s employees or any sub-processors of data.
        \t1.2. The Parties seek to implement a data consent agreement that complies with the requirements of the current data protection legal framework (e.g. the GDPR). Therefore, this Agreement shall apply to any processing of personal data carried out pursuant to the current data protection legislation.
        \t1.3. This Agreement includes a human-readable section, which constitutes the legally binding contract between the Parties, and a corresponding Machine-Readable (MR) section, provided in the Appendix A1, to facilitate automated processing and enforcement.
        """

    ctx.append(scope.strip() + "\n")

    # 2. DEFINITIONS
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

    # 3. PURPOSE OF THE AGREEMENT
    ctx.append("3. PURPOSE OF THE AGREEMENT.")
    ctx.append(
        "3.1. The purpose of this Agreement is to define the terms and conditions governing the sharing of data between the Data Provider and the Data Consumer. In particular, the Data Provider grants consent for the Data Consumer to process the data, as further detailed herein.")
    ctx.append(
        f"3.2. Data Provider can revoke their consent at any time by sending an email to {rights_email}, without prejudice to the legitimacy of the consent-based processing prior to its revocation.\n")

    # 4. DESCRIPTION OF DATA
    ctx.append("4. DESCRIPTION OF DATA.")
    ctx.append("\t4.1. The Data to be processed under this Agreement is described as follows:")
    ctx.append(_description_41_natural(
        title, price, uri, policy_url, eco_gen, eco_srv,
        description, type_of_data, data_format, data_size, tags
    ))

    if geographic_scope and temporal_coverage:
        ctx.append(
            f"\t4.2. This data set contains the performance indicators of marketing campaigns in [{geographic_scope}] "
            f"concerning the {categories} business verticals within the defined time period {temporal_coverage}. "
            "The information provided at keyword level offer the possibility of generating detail description of the society interests and trends.\n")
        ctx.append("\t4.3. The Machine-Readable (MR) version of the description of data (including its URI, description, format, size, associated tags, and environmental cost metrics) is presented in the Appendix A1.\n")

    else:
        ctx.append(
        "\t4.2. The Machine-Readable (MR) version of the description of data (including its URI, description, format, size, associated tags, and environmental cost metrics) is presented in the Appendix A1.\n")


    # 5. DATA USE – PERMITTED PURPOSES
    ctx.append("5. DATA USE – PERMITTED PURPOSES.")
    ctx.append(
        "\t5.1. The Shared Data shall be used by the Data Consumer solely for the permitted purpose(s) set out in Clauses 7 and 8.")
    ctx.append("\t5.2. No other use is permitted without prior written consent of the Data Provider.\n")

    # 6. GENERAL OBLIGATIONS OF THE PARTIES
    ctx.append("6. GENERAL OBLIGATIONS OF THE PARTIES.")
    ctx.append(
        "\t6.1. Data Consumer is obliged to fulfill their obligations hereunder, including the processing of the personal data processed, to comply with the applicable data protection law and to apply the basic principles for the protection of personal data, such as the principles of necessity, relevance, confidentiality, availability and integrity. The processing of personal data will also be carried out in accordance with the decisions of the competent Data Protection Authority, the working party under Article 29 of Directive 95/46/EC and the European Data Protection Board under Article 68 of the GDPR.")
    ctx.append("\t6.2. The Data Provider shall ensure that the Data shared is accurate, complete, and up to date.")
    ctx.append(
        "\t6.3. The Data Consumer shall not transmit, disclose, tolerate or provide access to the Data to any third party without the prior written consent of the Data Provider, at its sole discretion, unless expressly required to do so under applicable law.\n")

    # 7. POLICIES AND RULES (Permission only)
    ctx.append("7. POLICIES AND RULES.")
    ctx.append("7.1. The Parties must comply with the following permission rules:")
    # ctx.append("\t7.1. Permission")
    if permissions:
        for p in permissions:
            ctx.append(f"\t\t• {str(p).strip()}")
    else:
        ctx.append("\t\t(none)")
    ctx.append("\t7.2. The Machine-Readable (MR) version of policies and rules is presented in the Appendix A1.\n")

    custom_sections = []
    # 8. CUSTOM ARRANGEMENTS
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

    # 9. DATA PROTECTION (use updated rights language)
    ctx.append("9. DATA PROTECTION.")
    ctx.append(
        f"\t9.1. Data Consumer must ensure that Data Provider’s personal data is kept confidential and that Data Provider exercise their rights of access, correction, deletion, restriction, portability and objection by sending an email to {rights_email}.")
    ctx.append(
        "\t9.2.\tRight of correction. The Data Provider is entitled to require Data Consumer without undue delay to correct inaccurate personal data. Having regard to the purposes of the processing, the Data Provider is entitled to require the completion of incomplete personal data, including among others through a supplementary statement.")
    ctx.append(
        "\t9.3.\tRight of deletion. The Data Provider is entitled to ask Data Consumer to delete personal data without undue delay if: (a) the personal data is no longer necessary in relation to the purposes for which it was collected or otherwise processed; (b) the Data Provider has revoked the consent on which the processing is based and there is no other legal basis for the processing; (c) the Data Provider objects to the processing and there are no compelling legitimate grounds for the processing; (d) the personal data have been processed illegally; (e) data must be deleted so that the controller’s legal obligation is respected; and (f) personal data has been collected in connection with the provision of services in the information society. Requests for deletion of personal data are processed within one (1) month. If personal data is disclosed, the Data Consumer, taking into account the available technology and implementation costs, shall take reasonable steps, including technical measures, to inform third parties processing such data that the Data Provider has requested the deletion of any links to such data or copies or replications of personal data. The Data Consumer may retain Data Provider’s personal information in order to comply with the law, protect their rights, resolve disputes or enforce their agreements.")
    ctx.append(
        "\t9.4.\tRight to restriction of processing. The Data Provider is entitled to obtain from Data Consumer restriction of processing where one of the following applies: (a) the accuracy of the personal data is contested by the data subject, for a period enabling the controller to verify the accuracy of the personal data; (b) the processing is unlawful and the data subject opposes the erasure of the personal data and requests the restriction of their use instead; (c) the controller no longer needs the personal data for the purposes of the processing, but they are required by the data subject for the establishment, exercise or defence of legal claims; (d) the data subject has objected to processing pursuant to Article 21(1) GDPR pending the verification whether the legitimate grounds of the controller override those of the data subject. Where processing has been restricted, such personal data shall, with the exception of storage, only be processed with the data subject’s consent or for the establishment, exercise or defence of legal claims or for the protection of the rights of another natural or legal person or for reasons of important public interest of the Union or of a Member State. A data subject who has obtained restriction of processing shall be informed by the controller before the restriction of processing is lifted.")
    ctx.append(
        "\t9.5.\tRight to data portability. The Data Provider is entitled to receive the personal data concerning them, which they have provided to a controller, in a structured, commonly used and machine-readable format and has the right to transmit those data to another controller without hindrance from the controller to which the personal data have been provided, where: (a) the processing is based on consent pursuant to point (a) of Article 6(1) GDPR or point (a) of Article 9(2) GDPR or on a contract pursuant to point (b) of Article 6(1) GDPR; and (b) the processing is carried out by automated means.")
    ctx.append(
        "\t9.6.\tRight to object. The Data Provider is entitled to object, on grounds relating to their particular situation, at any time to processing of personal data concerning them which is based on point (e) or (f) of Article 6(1) GDPR, including profiling based on those provisions. The controller shall no longer process the personal data unless the controller demonstrates compelling legitimate grounds for the processing which override the interests, rights and freedoms of the data subject / Data Provider or for the establishment, exercise or defence of legal claims.")
    ctx.append(
        "\t9.7.\tData Provider has the right to lodge a complaint with a supervisory authority, in particular in the member state of their habitual residence, place of work or place of the alleged infringement if they consider that the processing of personal data relating to them infringes the General Data Protection Regulation (EU) 2016/679 (GDPR).\n")

    # 10. TECHNICAL AND ORGANISATIONAL SECURITY MEASURES - DATA SHARING MECHANISMS
    ctx.append("10. TECHNICAL AND ORGANISATIONAL SECURITY MEASURES - DATA SHARING MECHANISMS.")
    ctx.append(
        "\t10.1. Data Consumer shall implement and maintain, from the outset and before accessing the Data, appropriate technical and organisational measures, in accordance with current best practice and the state of the art in the relevant sector of activity, taking into account the implementation costs, and the nature, scope, circumstances and purpose of the processing, as well as the different probability of occurrence and the severity of the risk of the rights and freedoms of the persons concerned, in order to protect the Data being processed against accidental or unlawful destruction or accidental loss (including erasure), alteration (including destruction), modification, unauthorised disclosure, use or access and any other unlawful form of processing. Such measures will include, but shall not be limited to the pseudonymisation and encryption of Data, where appropriate; the ability to ensure the ongoing confidentiality, integrity, availability and resilience of processing systems and services on an ongoing basis; the ability to restore the availability and access to the Data in a timely manner in the event of a physical or technical incident, including a Data Breach; a process for regularly testing, assessing and evaluating the effectiveness of the technical and organisational measures in order to ensure the security of the processing of Data.")
    ctx.append(
        "\t10.2. In assessing the appropriate level of security, Data Consumer shall take account in particular of the risks that are presented by processing, in particular from a Personal Data Breach (as defined under GDPR).")
    ctx.append(
        "\t10.3. Data Consumer agrees to implement and maintain data-sharing mechanisms that: (a) comply with all applicable laws and regulations; and (b) ensure the confidentiality and integrity of data during transmission.")
    ctx.append(
        "\t10.4. Data sharing pursuant to this Agreement shall be conducted exclusively through secure communication channels.")
    ctx.append("\t10.5. All data transfers must be encrypted during transmission and comprehensively logged.\n")

    # 11. CONFIDENTIALITY
    ctx.append("11. CONFIDENTIALITY.")
    ctx.append("\t11.1. Data Consumer agrees to treat all Data shared under this Agreement as confidential.")
    ctx.append(
        "\t11.2. Unless otherwise agreed, each Party shall maintain absolute confidentiality with respect to this Agreement, its activities and any information and documentation relating to the other Party (or anyone on its behalf) of which it becomes aware as a result of its cooperation with the other Party.")
    ctx.append(
        "\t11.3. The confidentiality and non-disclosure obligations set forth herein shall remain indefinitely, also following the termination and/or expiration of this Agreement and the cooperation of the Parties.\n")

    # 12. LIABILITY
    ctx.append("12. LIABILITY.")
    ctx.append(
        "Each Party shall be fully liable to the other for any act and/or omission by itself and/or any of its employees, agents or assistants and/or any of its subcontractors. The defaulting Party is obliged to compensate its counterparty for any positive and/or consequential damage and/or moral damage that it or a third party (natural or legal person), to which the defaulting party is liable, may suffer from a breach of the obligations arising hereunder by it (i.e. the defaulting party), its employees, agents, assistants and/or any subcontractors.\n")

    # 13. CONTACT
    ctx.append("13. CONTACT.")
    ctx.append(
        "\t13.1. With respect to any matter relating to this Agreement, the Parties shall communicate with each other through the contact persons, addresses, emails and telephone numbers listed in Appendix A2 of this Agreement.")
    ctx.append(
        "\t13.2. In the event of a change in the contact details, each Party shall inform the other Party in writing and without delay of the change.")
    ctx.append(
        "\t13.3. Any statement or notice sent between the Parties via email, as addressed, shall become effective upon receipt by the recipient. Any notice or communication sent by email shall be deemed received on the next business day following transmission (to the addresses indicated below), provided that no delivery failure notification is received by the sender.")
    ctx.append(
        "\t13.4. Notices made by post are deemed to have been delivered within seventy two (72) hours upon being sent, and if delivered by courier- on the date of the actual receipt signed by a representative of the recipient.\n")

    # 14. OTHER PROVISIONS
    ctx.append("14. OTHER PROVISIONS.")
    ctx.append(
        "\t14.1. If any term of this Agreement is declared invalid or unenforceable for any reason or cause, the validity of this Agreement shall not be affected, and the remaining terms shall remain in effect as if the invalid or unenforceable term had not been included herein.")
    ctx.append("\t14.2. This Agreement may be amended only by new written agreement between the Parties.")
    ctx.append(
        "\t14.3. The Parties acknowledge that in the event of any conflict between the provisions of this Agreement and other prior agreements governing the processing of data, the provisions herein shall prevail.")
    ctx.append(
        "\t14.4. In the event of any inconsistency between the terms of this Agreement and the Appendices, the provisions of this Agreement shall prevail.\n")

    # 15. DISPUTE RESOLUTION
    ctx.append("15. DISPUTE RESOLUTION.")
    ctx.append(
        "The Parties shall endeavour in good faith to resolve amicably any dispute and/or difference arising out of the Agreement and/or the Appendices thereto, which form an undivided and integral part thereof. In the event of failure to resolve any dispute / difference amicably, the courts of the country in which the Data Provider is located shall be exclusively responsible for its resolution.\n")

    # 16. GOVERNING LAW AND JURISDICTION
    ctx.append("16. GOVERNING LAW AND JURISDICTION.")
    ctx.append(
        "\t16.1. This Agreement and any non-contractual obligations arising out of or in connection with it shall be governed by and interpreted in accordance with the laws of the country in which the Data Provider is located.")
    ctx.append(
        "\t16.2. Each Party irrevocably submits to the exclusive jurisdiction of the courts of the country in which the Data Provider is located over any claim or matter arising under, or in connection with, this Agreement.\n")

    # 17. SIGNATURES (term_text included)
    sig = f"""17. SIGNATURES.
IN WITNESS WHEREOF, this Agreement has been entered into on the date stated at the beginning of it and should remain in force for {term_text}



SIGNED by {provider_fullname}


                                                    Signature
                                                    
                                                    ........................................
                                                    
                                                    Date
                                                    
                                                    ........................................



SIGNED by 
Duly authorised for and on behalf of {consumer_org}


                                                    Signature
                                                    
                                                    
                                                    ........................................
                                                    Name
                                                    
                                                    
                                                    ........................................
                                                    Date
                                                    
                                                    ........................................
"""
    ctx.append(sig.strip() + "\n")

    # 18. Appendix (A1: ODRL + Data Resource; A2 contacts)
    ctx.append("18. Appendix")
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
        rules = (odrl or {}).get(rule_type, []) or []
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

    # RULE_IRI = {
    #     "permission": "http://www.w3.org/ns/odrl/2/Permission",
    #     "prohibition": "http://www.w3.org/ns/odrl/2/Prohibition",
    #     "obligation": "http://www.w3.org/ns/odrl/2/Obligation",
    #     "duty": "http://www.w3.org/ns/odrl/2/Duty",
    # }
    #
    # type_counter = 1
    # for rule_type in ("permission", "prohibition", "obligation", "duty"):
    #     rules = (odrl or {}).get(rule_type, []) or []
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
    #             if purpose_idx is None:
    #                 first = all_constraints[0]
    #                 purpose = _to_str(first.get("rightOperand", ""))
    #                 rest_constraints = all_constraints[1:]
    #             else:
    #                 purpose = _to_str(all_constraints[purpose_idx].get("rightOperand", ""))
    #                 rest_constraints = [c for j, c in enumerate(all_constraints) if j != purpose_idx]
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
    if isinstance(d.get("resource_description", {}), dict):
        for sub_key, sub_val in d.get("resource_description", {}).items():
            if isinstance(sub_val, dict):
                non_empty = {k: v for k, v in sub_val.items() if v not in (None, "", [])}
                pretty = non_empty if non_empty else sub_val
                ctx.append(f"\t\t\t• {str(sub_key).replace('_', ' ').title()}: {pretty}")
            else:
                ctx.append(f"\t\t\t• {str(sub_key).replace('_', ' ').title()}: {sub_val}")
    ctx.append("")

    # A2 contacts
    ctx.append("\tA2. Communication and Persons in Charge\n")
    if cp:
        ctx.append(render_provider_individual(cp))
    else:
        ctx.append("\t\tA2.1 Data Provider")
        ctx.append("\t\t\t(none)\n")
    if cc:
        ctx.append(render_consumer_org(cc))
    else:
        ctx.append("\t\tA2.2 Data Consumer")
        ctx.append("\t\t\t(none)\n")

    ctx.append("\n")

    print("End call get_consent_contract_text function \n\n")
    return "\n".join(ctx)





import json


def save_ca_outputs(
        data,
        text_path: str = "ca_contract.txt",
        json_path: str = "ca_contract.json",
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
    text = get_consent_contract_text(data)


    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text)



    return text_path, json_path
