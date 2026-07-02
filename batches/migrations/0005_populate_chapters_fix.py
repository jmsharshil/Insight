"""
Data migration: Populate subjects and chapters for Company Secretary (Fix)
────────────────────────────────────────────────────────────────────────────────
Creates subjects and chapters. Fixes issue where production course code didn't
match CRS-0007. This version smartly finds the course or creates it.
"""

from django.db import migrations

CHAPTER_DATA = {
    "CSEET": [
        {
            "name": "BUSINESS COMMUNICATION",
            "chapters": [
                "Essentials of Good English",
                "Communication",
                "Business Correspondence",
                "Common Business Terminologies",
            ],
        },
        {
            "name": "FUNDAMENTS OF ACCOUNTS",
            "chapters": [
                "Basics Concept and Principles of Accounting",
                "Accounting Process",
                "Bank Reconciliation Statement",
                "Depreciation and Amortization",
                "Preparation of Final Accounts for Sole Proprietorship",
                "Partnership and LLP Accounts",
                "Introduction to Company Accounts",
                "Accounting for Non-Profit Organizations",
            ],
        },
        {
            "name": "ECONOMICS AND BUSINESS ENVIROMENT",
            "chapters": [
                "Basics of Demand and Supply and Forms of Market Competition",
                "National Income Accounting and Related Concepts",
                "Indian Union Budget",
                "Indian Financial Markets",
                "Indian Economy",
                "Entrepreneurship Scenario",
                "Business Environment",
                "Key Government Institutions",
                "Global Environment",
                "Environmental Governance",
                "AI and Business Environment",
                "Elements of Corporate Governance",
            ],
        },
        {
            "name": "BUSINESS LAW AND MANAGEMENT",
            "chapters": [
                "Introduction to Law",
                "Elements of Company Law",
                "Elements of Law of Contracts",
                "Elements of Law relating to Partnership and Limited Liability Partnership",
                "Elements of Law relating to Sale of Goods",
                "Elements of Law relating to Negotiable Instruments",
                "Introduction to Management",
                "Functions of Management",
                "Principles of Management and Modern Approaches",
                "Management Knowledge for Company Secretaries",
            ],
        },
    ],
    "CS Executive": [
        {
            "name": "Jurisprudence, Interpretation and General Laws",
            "chapters": [
                "SOURCES OF LAW",
                "CONSTITUTION OF INDIA",
                "INTERPRETATION OF STATUES",
                "ADMINISTRATIVE LAWS",
                "LAW OF TORTS",
                "LAW RELATING TO CIVIL PROCEDURE",
                "LAWS RELATING TO CRIME AND ITS PROCEDURE",
                "LAW RELATING TO EVIDENCE",
                "LAW RELATING TO SPECIFIC RELIEF",
                "LAW RELATING TO LIMITATION",
                "LAW RELATING TO ARBITRATION, MEDITATION AND CONCILATION",
                "INDIAN STAMP LAW",
                "LAW RELATING TO REGISTRATION OF DOCUMENTS",
                "RIGHT TO INFORMATION LAW",
                "LAW RELATING TO INFORMATION TECHNOLOGY",
                "CONTRACT LAW",
                "LAW RELATING TO SALE OF GOODS",
                "LAW RELATING TO NEGOTIABLE INSTRUMENTS",
            ],
        },
        {
            "name": "COMPANY LAW",
            "chapters": [
                "INTRODUCTION TO COMPANY LAW",
                "LEGAL STATUS AND TYPES OF REGISTERED COMPANIES",
                "MEMORANDUM AND ARTICLES OF ASSOCIATIONS AND ITS ALTERATION",
                "SHARE AND SHARE CAPITAL-CONCEPTS",
                "MEMBERS AND SHAREHOLDERS",
                "DEBT INSTRUMENTS-CONCEPTS",
                "CHARGES",
                "DISTRIBUTION OF PROFITS",
                "ACCOUNTS AND AUDITORS",
                "COMPROMISE, ARRANGEMENT AND AMALGAMATIONS-CONCEPTS",
                "DORMANT COMPANY",
                "INSPECTION, INQUIRY AND INVESTIGATION",
                "GENERAL MEETINGS",
                "DIRECTORS",
                "BOARD COMPOSITION AND POWERS OF THE BOARD",
                "MEETINGS OF BOARD AND ITS COMMITTEES",
                "CORPORATE SOCIAL RESPONSIBILITY-CONCEPTS",
                "ANNUAL REPORT-CONCEPTS",
            ],
        },
        {
            "name": "Setting Up of Business and Industrial & Labour Laws",
            "chapters": [
                "SELECTION OF BUSINESS ORGANIZATION",
                "CORPORATE ENTITIES-COMPANIES",
                "LIMITED LIABILITY PARTNERSHIP",
                "STARTUPS AND ITS REGISTRATION",
                "MICRO, SMALL AND MEDIUM ENTERPRISES",
                "CONVERSION OF BUSINESS ENTITIES",
                "NON-CORPORATE ENTITIES",
                "FINANCIAL SERVICES ORGANIZATION",
                "BUSINESS COLLABRATIONS",
                "SETTING UP OF BRANCH OFFICE/LIASIAN OFFICE/WHOLLY OWNED SUBSIDIARY BY FOREIGN COMPANY",
                "SETTING UP OF BUSINESS OUTSIDE INDIA AND ISSUE RELATING THERETO",
                "IDENTIFYING LAWS APPLICABLE TO VARIOUS INDUSTRIES AND THEIR INITIAL COMPLIANCES",
                "VARIOUS INITIAL REGISTRATION AND LICENSES",
                "CONSTITUTION AND LABOUR LAWS",
                "EVALUTION OF LABOUR LEGISLATION AND NEED OF LABOUR CODE",
                "LAW OF WELFARE & WORKING CONDITION",
                "LAW OF INDUSTRIAL RELATIONS",
                "LAW OF WAGES",
                "SOCIAL SECURITY LEGISLATIONS",
                "SEXUAL HARASSMENT OF WOMEN AT WORKPLACE (PREVENTION, PROHIBITION AND REDRESSAL) ACT, 2013",
            ],
        },
        {
            "name": "Corporate Accounting and Financial Management",
            "chapters": [
                "INTRODUCTION TO ACCOUNTING",
                "INTRODUCTION TO CORPORATE ACCOUNTING",
                "ACCOUNTING STANDARDS(AS)",
                "ACCOUNTING FOR SHARE CAPITAL",
                "ACCOUNTING FOR DEBENTURES",
                "RELATED ASPECTS OF COMPANY ACCOUNTS",
                "CONSOLIDATION OF ACCOUNTS",
                "FINANCIAL STATEMENTS ANALYSIS",
                "CASH FLOWS",
                "FORECASTING FINANCIAL STATEMENTS",
                "INTRODUCTION",
                "TIME VALUE OF MONEY",
                "CAPITAL BUDGETING",
                "COST OF CAPITAL",
                "CAPITAL STRUCTURE",
                "DIVIDEND DECISIONS",
                "WORKING CAPITAL MANAGEMENT",
                "SECURITY ANALYSIS",
                "OPERATIONAL APPROACH TO FINANCIAL DECISION",
            ],
        },
        {
            "name": "Capital Markets and Securities Laws",
            "chapters": [
                "BASICS OF CAPITAL MARKET",
                "SECONDARY MARKET IN INDIA",
                "SECURITIES CONTRACTS (REGULATION) ACT, 1956",
                "SECURITIES AND EXCHANGE BOARD OF INDIA",
                "LAWS GOVERNING TO DEPOSITORIES AND DEPOSITORY PARTICIPANTS",
                "SECURITIES MARKET INTERMEDIARIES",
                "INTERNATIONAL FINANCIAL SERVICES CENTRES AUTHORITY (IFSCA)",
                "ISSUE OF CAPITAL & DISCLOSURE REQUIREMENTS",
                "SHARE BASED EMPLOYEE BENEFITS AND SWEAT EQUITY",
                "ISSUE AND LISTING OF NON-CONVERTIBLE SECURITIES",
                "LISTING OBLIGATIONS AND DISCLOSURE REQUIREMENTS",
                "ACQUISITION OF SHARES AND TAKEOVERS – CONCEPTS",
                "PROHIBITION OF INSIDER TRADING",
                "PROHIBITION OF FRAUDULENT AND UNFAIR TRADE PRACTICES RELATING TO SECURITIES MARKET",
                "DELISTING OF EQUITY SHARES",
                "BUY-BACK OF SECURITIES",
                "MUTUAL FUNDS",
                "COLLECTIVE INVESTMENT SCHEMES",
            ],
        },
        {
            "name": "Economic, Commercial and Intellectual Property Laws",
            "chapters": [
                "LAW RELATING FOREIGN EXCHANGE MANAGEMENT",
                "FOREIGN DIRECT INVESTMENTS – REGULATIONS & POLICY",
                "OVERSEAS DIRECT INVESTMENT",
                "EXTERNAL COMMERCIAL BORROWINGS (ECB)",
                "FOREIGN TRADE POLICY & PROCEDURE",
                "LAW RELATING TO SPECIAL ECONOMIC ZONES",
                "LAW RELATING TO FOREIGN CONTRIBUTION REGULATION",
                "PREVENTION OF MONEY LAUNDERING",
                "LAW RELATING TO FUGITIVE ECONOMIC OFFENDERS",
                "LAW RELATING TO BENAMI TRANSACTIONS & PROHIBITION",
                "COMPETITION LAW",
                "LAW RELATING TO CONSUMER PROTECTION",
                "LEGAL METROLOGY",
                "REAL ESTATE REGULATION AND DEVELOPMENT LAW",
                "INTELLECTUAL PROPERTY RIGHTS",
                "LAW RELATING TO PATENTS",
                "LAW RELATING TO TRADE MARKS",
                "LAW RELATING TO COPYRIGHT",
                "LAW RELATING TO GEOGRAPHICAL INDICATIONS OF GOODS",
                "LAW RELATING TO DESIGNS",
            ],
        },
        {
            "name": "Tax Laws and Practice",
            "chapters": [
                "DIRECT TAXES – AT A GLANCE",
                "BASIC CONCEPT OF INCOME TAX",
                "INCOMES WHICH DO NOT FORM PART OF TOTAL INCOME",
                "INCOME UNDER THE HEAD HOUSE PROPERTY",
                "PROFITS AND GAINS FROM BUSINESS AND PROFESSION",
                "CAPITAL GAINS",
                "INCOME FROM OTHER SOURCES",
                "CLUBBING PROVISIONS AND SET OFF AND / OR CARRY FORWARD OF LOSSES",
                "DEDUCTIONS",
                "COMPUTATION OF TOTAL INCOME AND TAX LIABILITY OF VARIOUS ENTITIES",
                "CLASSIFICATION AND TAX INCIDENCE ON COMPANIES",
                "PROCEDURAL COMPLIANCE",
                "CONCEPT OF INDIRECT TAXES AT A GLANCE",
                "BASICS OF GOODS AND SERVICES TAX 'GST'",
                "LEVY AND COLLECTION OF GST",
                "TIME, VALUE & PLACE OF SUPPLY",
                "INPUT TAX CREDIT & COMPUTATION OF GST LIABILITY",
                "PROCEDURAL COMPLIANCE UNDER GST",
                "OVERVIEW OF CUSTOMS ACT",
            ],
        },
    ],
    "CS Professional": [
        {
            "name": "ESG (Environment, Social & Governance)",
            "chapters": [
                "CONCEPTUAL FRAMEWORK OF CORPORATE GOVERNANCE",
                "LEGISLATIVE FRAMEWORK OF CORPORATE GOVERNANCE IN INDIA",
                "BOARD EFFECTIVENESS/BUILDING BETTER BOARDS",
                "BOARD PROCESSES THROUGH SECRETARIAL STANDARDS",
                "BOARD COMMITTEES",
                "(THIS LESSON HAS BEEN MERGED WITH LESSON 3)",
                "CONCEPT OF GOVERNANCE IN PROFESSIONAL MANAGED COMPANY & PROMOTERS DRIVEN COMPANY",
                "BOARD DISCLOSURES AND WEBSITE DISCLOSURES",
                "DATA GOVERNANCE",
                "STAKEHOLDERS RIGHTS",
                "BUSINESS ETHICS, CODE OF CONDUCT AND ANTI-BRIBERY",
                "BOARD'S ACCOUNTABILITY ON ESG",
                "ENVIRONMENT",
                "CORPORATE SOCIAL RESPONSIBILITY (CSR)",
                "GREEN INITIATIVES",
                "GOVERNANCE INFLUENCERS",
                "EMPOWERMENT OF THE COMPANY SECRETARY PROFESSION",
                "RISK MANAGEMENT",
                "SUSTAINABILITY AUDIT; ESG RATING; EMERGING MANDATES FROM GOVERNMENT AND REGULATORS",
                "INTEGRATED REPORTING FRAMEWORK; GLOBAL REPORTING INITIATIVE FRAMEWORK; BUSINESS RESPONSIBILITY & SUSTAINABILITY REPORTING",
            ],
        },
        {
            "name": "Drafting, Appearances and Pleadings",
            "chapters": [
                "TYPES OF DOCUMENTS",
                "GENERAL PRINCIPLES OF DRAFTING",
                "LAWS RELATING TO DRAFTING AND CONVEYANCING",
                "DRAFTING OF AGREEMENTS, DEEDS AND DOCUMENTS",
                "DRAFTING OF COMMERCIAL CONTRACTS",
                "DOCUMENTS UNDER COMPANIES ACT, 2013",
                "ART OF OPINION WRITING",
                "COMMERCIAL CONTRACT MANAGEMENT",
                "JUDICIAL & ADMINISTRATIVE FRAMEWORK",
                "PLEADINGS",
                "ART OF ADVOCACY AND APPEARANCES",
                "APPLICATIONS, PETITIONS AND APPEALS UNDER COMPANIES ACT, 2013",
                "ADJUDICATIONS AND APPEALS UNDER SEBI LAWS",
                "APPEARANCE BEFORE OTHER REGULATORY AND QUASI-JUDICIAL AUTHORITIES",
            ],
        },
        {
            "name": "Compliance Management, Audit and Due Diligence",
            "chapters": [
                "COMPLIANCE FRAMEWORK",
                "DOCUMENTATION & MAINTENANCE OF RECORDS",
                "SIGNING AND CERTIFICATION",
                "LEGAL FRAMEWORK GOVERNING COMPANY SECRETARIES",
                "VALUES, ETHICS AND PROFESSIONAL CONDUCT",
                "NON-COMPLIANCES, PENALTIES AND ADJUDICATIONS",
                "RELIEFS AND REMEDIES",
                "CONCEPTS OF VARIOUS AUDITS",
                "AUDIT ENGAGEMENT",
                "AUDIT PRINCIPLES AND TECHNIQUES",
                "AUDIT PROCESS AND DOCUMENTATION",
                "FORMING AN OPINION & REPORTING",
                "SECRETARIAL AUDIT",
                "INTERNAL AUDIT & PERFORMANCE AUDIT",
                "PEER REVIEW AND QUALITY REVIEW",
                "DUE DILIGENCE",
            ],
        },
        {
            "name": "Intellectual Property Rights",
            "chapters": [
                "INTRODUCTION",
                "TYPES OF INTELLECTUAL PROPERTY",
                "ROLE OF INTERNATIONAL INSTITUTIONS",
                "INDIAN PATENT LAW AND ITS DEVELOPMENTS",
                "PATENT DATABASES & PATENT INFORMATION SYSTEM",
                "PATENT DOCUMENTATION, EXAMINATION AND INFRINGEMENT",
                "TRADEMARKS",
                "COPYRIGHTS",
                "INDUSTRIAL DESIGNS",
                "GEOGRAPHICAL INDICATIONS",
                "LAYOUT- DESIGNS OF INTEGRATED CIRCUITS",
                "PROTECTION OF TRADE SECRETS",
                "BIOLOGICAL DIVERSITY",
                "PROTECTION OF PLANT VARIETIES",
                "BUSINESS CONCERNS IN COMMERCIALIZING INTELLECTUAL PROPERTY RIGHTS",
            ],
        },
        {
            "name": "Strategic Management and Corporate Finance",
            "chapters": [
                "INTRODUCTION TO STRATEGIC MANAGEMENT",
                "ANALYZING THE EXTERNAL AND INTERNAL ENVIRONMENT",
                "BUSINESS POLICY AND FORMULATION OF FUNCTIONAL STRATEGY",
                "STRATEGIC ANALYSIS AND PLANNING",
                "COMPETITIVE POSITIONING",
                "MANAGING THE MULTI-BUSINESS FIRM AND ANALYZING STRATEGIC EDGE",
                "SOURCES OF CORPORATE FUNDING",
                "RAISING OF FUNDS FROM EQUITY AND PROCEDURAL ASPECTS – PUBLIC FUNDING",
                "REAL ESTATE INVESTMENT TRUSTS",
                "INFRASTRUCTURE INVESTMENT TRUSTS",
                "RAISING OF FUNDS – PRIVATE FUNDING",
                "RAISING OF FUNDS – NON FUND BASED",
                "AN OVERVIEW ON LISTING AND ISSUANCE OF SECURITIES IN INTERNATIONAL FINANCIAL SERVICES CENTRE",
                "RAISING OF FUNDS FROM DEBT AND PROCEDURAL ASPECTS",
                "FOREIGN FUNDING-INSTITUTIONS",
                "FOREIGN FUNDING-INSTRUMENTS, LAWS AND PROCEDURES",
                "ROLE OF INTERMEDIARIES IN FUND RAISING",
                "PROJECT EVALUATION",
            ],
        },
        {
            "name": "Corporate Restructuring, Valuation and Insolvency",
            "chapters": [
                "TYPES OF CORPORATE RESTRUCTURING",
                "ACQUISITION OF COMPANY/BUSINESS",
                "PLANNING & STRATEGY",
                "PROCESS OF M&A TRANSACTIONS",
                "DOCUMENTATION-MERGER & AMALGAMATION",
                "ACCOUNTING IN CORPORATE RESTRUCTURING: CONCEPT AND ACCOUNTING TREATMENT",
                "TAXATION & STAMP DUTY ASPECTS OF CORPORATE RESTRUCTURING",
                "REGULATION OF COMBINATIONS",
                "REGULATORY APPROVALS OF SCHEME",
                "FAST TRACK MERGERS",
                "CROSS BORDER MERGERS",
                "OVERVIEW OF BUSINESS VALUATION",
                "VALUATION OF BUSINESS AND ASSETS FOR CORPORATE RESTRUCTURING",
                "INSOLVENCY",
                "APPLICATION FOR CORPORATE INSOLVENCY RESOLUTION PROCESS",
                "ROLE, FUNCTIONS AND DUTIES OF IP/IRP/RP",
                "RESOLUTION STRATEGIES",
                "CONVENING AND CONDUCT OF MEETINGS OF COMMITTEE OF CREDITORS",
                "PREPARATION & APPROVAL OF RESOLUTION PLAN",
                "PRE-PACKAGED INSOLVENCY RESOLUTION PROCESS",
                "CROSS BORDER INSOLVENCY",
                "LIQUIDATION ON OR AFTER FAILING OF RESOLUTION PLAN",
                "VOLUNTARY LIQUIDATION",
                "DEBT RECOVERY & SARFAESI",
                "WINDING-UP BY TRIBUNAL UNDER THE COMPANIES ACT, 2013",
                "STRIKE OFF AND RESTORATION OF NAME OF THE COMPANY AND LLP",
            ],
        },
        {
            "name": "Insolvency and Bankruptcy Code",
            "chapters": [
                "INTRODUCTION TO INSOLVENCY AND BANKRUPTCY CODE",
                "CORPORATE INSOLVENCY RESOLUTION PROCESS",
                "RESOLUTION STRATEGIES",
                "FAST TRACK CORPORATE INSOLVENCY RESOLUTION PROCESS",
                "LIQUIDATION OF CORPORATE PERSON",
                "VOLUNTARY LIQUIDATION OF COMPANIES",
                "ADJUDICATION AND APPEALS FOR CORPORATE PERSONS",
                "PRE-PACKAGED INSOLVENCY RESOLUTION PROCESS",
                "DEBT RECOVERY & SECURITIZATION",
                "WINDING-UP BY TRIBUNAL",
                "INSOLVENCY RESOLUTION OF INDIVIDUAL AND PARTNERSHIP FIRMS",
                "BANKRUPTCY ORDER FOR INDIVIDUALS AND PARTNERSHIP FIRMS",
                "BANKRUPTCY FOR INDIVIDUALS AND PARTNERSHIP FIRMS",
                "FRESH START PROCESS",
                "PROFESSIONAL AND ETHICAL PRACTICES FOR INSOLVENCY PRACTITIONERS",
                "GROUP INSOLVENCY",
                "CROSS BORDER INSOLVENCY",
            ],
        },
    ],
}

def populate_chapters_smart(apps, schema_editor):
    """Smartly find course and create missing CourseLevels + Subjects + Chapters."""
    Course = apps.get_model("batches", "Course")
    CourseLevel = apps.get_model("batches", "CourseLevel")
    Subject = apps.get_model("batches", "Subject")
    Chapter = apps.get_model("batches", "Chapter")
    Organization = apps.get_model("auth_user", "Organization")

    course = Course.objects.filter(name__icontains="Company Secratory").first()
    if not course:
        course = Course.objects.filter(name__icontains="Company Secretary").first()
    
    if not course:
        level = CourseLevel.objects.filter(name__icontains="CS Executive").first()
        if level:
            course = level.course
            
    if not course:
        print("\n  ⚠️  No 'Company Secretary' course found in DB! Creating one automatically.")
        org = Organization.objects.first()
        course = Course.objects.create(name="Company Secretary", organization=org)
        
    print(f"\n  🎯 Using Course: {course.code} - {course.name}")

    # Find the current max sequence for Subject code
    last_subject = Subject.objects.filter(code__startswith='SUB-').order_by('-code').first()
    if last_subject and last_subject.code:
        try:
            seq = int(last_subject.code.split('-')[-1])
        except Exception:
            seq = 0
    else:
        seq = 0

    for idx, (level_name, subjects_data) in enumerate(CHAPTER_DATA.items(), start=1):
        level, created = CourseLevel.objects.get_or_create(
            course=course, 
            name=level_name,
            defaults={
                "order": idx,
                "course_type": "cseet" if level_name == "CSEET" else "standard",
                "organization": course.organization,
            }
        )
        if created:
            print(f"  ✨ Created CourseLevel '{level_name}'")

        for subj_data in subjects_data:
            subject = Subject.objects.filter(level=level, name=subj_data["name"]).first()
            if not subject:
                seq += 1
                new_code = f"SUB-{seq:04d}"
                subject = Subject.objects.create(
                    level=level,
                    name=subj_data["name"],
                    organization=course.organization,
                    code=new_code
                )
                print(f"  ✨ Created subject: {subject.name}")
            else:
                print(f"  📌 Exists subject: {subject.name}")
            
            for order, ch_name in enumerate(subj_data["chapters"], start=1):
                Chapter.objects.get_or_create(
                    subject=subject,
                    order=order,
                    defaults={
                        "name": ch_name,
                        "is_active": True,
                        "duration_hours": 0,
                    },
                )

def reverse_chapters(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ("batches", "0004_populate_chapters"),
    ]

    operations = [
        migrations.RunPython(populate_chapters_smart, reverse_chapters),
    ]
