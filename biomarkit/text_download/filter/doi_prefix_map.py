# Maps DOI prefixes to the API client that can download them. Used to route papers whose Scopus publisher is missing
# or does not map to a client via publisher_map. Keys must match the client keys in apis/map.py. Only prefixes of
# publishers with a client are worth listing: papers with any other prefix only get the open-access routes anyway.

doi_prefix_map = {
    "elsevier": ["10.1016",   # Elsevier
                 "10.1006"],  # Academic Press

    "springer": ["10.1007",   # Springer
                 "10.1023",   # Kluwer Academic Publishers
                 "10.1038",   # Nature
                 "10.1186"],  # BioMed Central

    "wiley": ["10.1111",      # Wiley-Blackwell
              "10.1002",      # Wiley
              "10.1046",      # Blackwell Publishing
              "10.2135"],     # Crop Science Society of America (published by Wiley)

    "taylor_and_francis": ["10.1080",
                           "10.1081"],

    "mdpi": ["10.3390"],
    "frontiers": ["10.3389"],
    "copernicus": ["10.5194"],
    "american_phytopathological_society": ["10.1094"],
}
