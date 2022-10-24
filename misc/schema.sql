CREATE TABLE 'Config' (
    'ranfirsttime' BOOLEAN NOT NULL DEFAULT 0,
);

CREATE TABLE 'Players' (
    'id' INTEGER PRIMARY KEY NOT NULL,
    'joined' DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    'left' DATETIME DEFAULT NULL,
    'messagecount' INTEGER NOT NULL DEFAULT 0,
    'lastmessage' DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE 'Motions' (
    'id' VARCHAR PRIMARY KEY NOT NULL,
    'authorid' INTEGER NOT NULL,
    'introduced' DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    'expires' DATETIME NOT NULL,
    'data' JSON NOT NULL,
    'votes' JSON NOT NULL
);

CREATE TABLE 'Offices' (
    'name' VARCHAR PRIMARY KEY NOT NULL,
    'roleid' INTEGER NOT NULL,
    'generation' INTEGER NOT NULL DEFAULT 1,
    'seats' INTEGER NOT NULL DEFAULT 1,
    'termlimit' INTEGER NOT NULL DEFAULT 0, /* 0 for no limits */
    'lastelection' DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    'termlength' INT NOT NULL DEFAULT 14,  /* Total Term length */
    'candidacydays' INT NOT NULL DEFAULT 7, /* The number of days in the term where people can run for office */
    'votingdays' INT NOT NULL DEFAULT 7, /* The number of days in the term where people can vote for office */
);

CREATE TABLE 'Officers' (
    'id' INTEGER PRIMARY KEY NOT NULL,
    'office' VARCHAR NOT NULL,
    'termsservedsuccessively' INTEGER NOT NULL DEFAULT 1,
    'termsmissedsuccessively' INTEGER NOT NULL DEFAULT 0,
    'termsservedtotal' INTEGER NOT NULL DEFAULT 1,
    'currentlyserving' BOOLEAN NOT NULL DEFAULT 1
);

CREATE TABLE 'RegularElections' (
    'office' VARCHAR PRIMARY KEY NOT NULL,
    'stage' VARCHAR NOT NULL DEFAULT "NOTRUNNING",
    'nextstage' DATETIME NOT NULL,
    'lastelection' DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    'termlength' INT NOT NULL DEFAULT 14,  /* Total Term length */
    'candidacydays' INT NOT NULL DEFAULT 7, /* The number of days in the term where people can run for office */
    'votingdays' INT NOT NULL DEFAULT 7, /* The number of days in the term where people can vote for office */
    'candidates' JSON,
    'votes' JSON
);
