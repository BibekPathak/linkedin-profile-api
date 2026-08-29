"""Unit tests for the mobile (p_mwlite) profile parser."""
from app.engine.parsing import parse_mobile_profile

RICH = """Profile | LinkedIn
Home
About this profile
Abhishek Pathak
Joined 2015
Abhishek Pathak
2nd
Premium member
AI Investments @ Sorin | PeerCapital | IndigoEdge | IIT Roorkee
Indian Institute of Technology, Roorkee
Sorin Investments
Bengaluru, Karnataka, India
500+ connections
About
I am an Investment Associate at an early stage VC firm.
Experience
Investment Associate
Sorin Investments
Aug 2024
-
Present
2 yrs 1 mo
Bengaluru, Karnataka, India
Sorin is a Series A/B Fund.
…more
See less
Education
Indian Institute of Technology, Roorkee
Bachelor's degree
Bachelor of Technology (B.Tech.), Chemical Engineering
2014
-
2018
Delhi Public School Ghaziabad
Secondary and Senior Secondary
2010
-
2014
Stoa School
General MBA
Jan 2022
-
Present
Skills
Microsoft Office
C++
Python
Accomplishments
10
Certifications
Introduction to Marketing
edX
…more
See less
Customer Analytics
Coursera
…more
See less
2
Languages
English
Hindi
"""

SELF = """Profile | LinkedIn
Share Profile
Bibek Pathak
Premium member
just trying
International Institute of Information Technology, Bhubaneswar
Smarbl Limited
Krishnanagar, West Bengal, India
474 connections
About
https://github.com/BibekPathak
…See more
See less
Edit
Featured
Open in app
Experience
Software Engineer
Smarbl Limited
Jan 2026
-
Present
8 mos
Pune City, Maharashtra, India
Have more experience?
Education
International Institute of Information Technology, Bhubaneswar
Bachelor of Technology - BTech
Computer Science
2022
-
May 2026
Skills
Add skills
Recommendations
Languages
Contact
"""


def test_rich_mobile_profile():
    r = parse_mobile_profile(RICH)
    assert r["name"] == "Abhishek Pathak"
    assert r["headline"] == "AI Investments @ Sorin | PeerCapital | IndigoEdge | IIT Roorkee"
    assert r["location"] == "Bengaluru, Karnataka, India"
    assert r["connections"] == "500+"
    assert r["about"] == "I am an Investment Associate at an early stage VC firm."
    assert len(r["experience"]) == 1
    e = r["experience"][0]
    assert e.title == "Investment Associate"
    assert e.company == "Sorin Investments"
    assert e.date_range == "Aug 2024 - Present · 2 yrs 1 mo"
    assert e.location == "Bengaluru, Karnataka, India"
    assert len(r["education"]) == 3
    assert r["education"][0].school == "Indian Institute of Technology, Roorkee"
    assert r["education"][0].date_range == "2014 - 2018"
    assert r["education"][2].school == "Stoa School"
    assert [s.name for s in r["skills"]] == ["Microsoft Office", "C++", "Python"]
    assert len(r["certifications"]) == 2
    assert r["certifications"][0].name == "Introduction to Marketing"
    assert r["certifications"][0].issuer == "edX"
    assert [l.name for l in r["languages"]] == ["English", "Hindi"]


def test_self_mobile_profile_empty_sections():
    r = parse_mobile_profile(SELF)
    assert r["name"] == "Bibek Pathak"
    assert r["headline"] == "just trying"
    assert r["location"] == "Krishnanagar, West Bengal, India"
    assert r["connections"] == "474"
    assert r["about"] == "https://github.com/BibekPathak"
    assert len(r["experience"]) == 1
    assert len(r["education"]) == 1
    assert r["education"][0].school == "International Institute of Information Technology, Bhubaneswar"
    assert r["skills"] == []
    assert r["certifications"] == []
    assert r["languages"] == []
