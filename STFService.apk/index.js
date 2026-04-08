{
    "steps": [
      {
        "type": "tap_selector",
        "by": "text",
        "value": "Facebook"
      },
      {
        "type": "wait_stable",
        "timeout": 8,
        "stable_duration": 0.5
      },
      {
        "type": "if_element",
        "by": "content-desc",
        "value": "Tìm kiếm",
        "timeout": 5,
        "then": [
          {
            "type": "tap_selector",
            "by": "content-desc",
            "value": "Tìm kiếm",
            "timeout": 4
          }
        ],
        "else": [
          {
            "type": "tap_ratio",
            "x": 0.87,
            "y": 0.035
          }
        ]
      },
      {
        "type": "wait_stable",
        "timeout": 4,
        "stable_duration": 0.4
      },
      {
        "type": "input_text",
        "text": "${GROUP_1}",
        "via": "u2"
      },
      {
        "type": "wait",
        "seconds": 2
      },
      {
        "type": "if_element",
        "by": "content-desc",
        "value": "${GROUP_1}",
        "timeout": 3,
        "then": [
          {
            "type": "key",
            "key": "enter"
          }
        ],
        "else": [
          {
            "type": "if_element",
            "by": "text",
            "value": "${GROUP_1}",
            "timeout": 3,
            "then": [
              {
                "type": "tap_selector",
                "by": "text",
                "value": "${GROUP_1}",
                "timeout": 3
              }
            ],
            "else": [
              {
                "type": "key",
                "key": "enter"
              },
              {
                "type": "wait",
                "seconds": 2
              },
              {
                "type": "if_element",
                "by": "text",
                "value": "Nhóm",
                "timeout": 3,
                "then": [
                  {
                    "type": "tap_selector",
                    "by": "text",
                    "value": "Nhóm",
                    "timeout": 3
                  }
                ],
                "else": [
                  {
                    "type": "if_element",
                    "by": "text",
                    "value": "Groups",
                    "timeout": 3,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "text",
                        "value": "Groups",
                        "timeout": 3
                      }
                    ],
                    "else": [
                      {
                        "type": "tap_selector",
                        "by": "text",
                        "value": ""
                      }
                    ]
                  },
                  {
                    "type": "tap_selector",
                    "by": "text",
                    "value": ""
                  }
                ]
              },
              {
                "type": "wait",
                "seconds": 2
              },
              {
                "type": "if_element",
                "by": "text",
                "value": "${GROUP_1}",
                "timeout": 5,
                "then": [
                  {
                    "type": "tap_selector",
                    "by": "text",
                    "value": ""
                  }
                ],
                "else": [
                  {
                    "type": "if_element",
                    "by": "content-desc",
                    "value": "${GROUP_1}",
                    "timeout": 3,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "content-desc",
                        "value": "${GROUP_1}",
                        "timeout": 3
                      }
                    ],
                    "else": [
                      {
                        "type": "tap_selector",
                        "by": "text",
                        "value": ""
                      }
                    ]
                  },
                  {
                    "type": "tap_selector",
                    "by": "text",
                    "value": ""
                  }
                ]
              },
              {
                "type": "tap_selector",
                "by": "text",
                "value": ""
              }
            ]
          },
          {
            "type": "tap_selector",
            "by": "text",
            "value": ""
          }
        ]
      },
      {
        "type": "wait_stable",
        "timeout": 6,
        "stable_duration": 0.5
      },
      {
        "type": "scroll_down",
        "repeats": 2
      },
      {
        "type": "wait_stable",
        "timeout": 3,
        "stable_duration": 0.4
      },
      {
        "type": "repeat",
        "count": "${SCROLLS_PER_GROUP}",
        "steps": [
          {
            "type": "extract",
            "strategy": "fb_posts",
            "expand_see_more": true
          },
          {
            "type": "random_pick",
            "branches": [
              {
                "weight": "${LIKE_WEIGHT}",
                "steps": [
                  {
                    "type": "if_element",
                    "by": "descriptionStartsWith",
                    "value": "Nút Thích.",
                    "timeout": 2,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "descriptionStartsWith",
                        "value": "Nút Thích.",
                        "timeout": 3
                      },
                      {
                        "type": "wait",
                        "seconds": 1
                      }
                    ]
                  }
                ]
              },
              {
                "weight": 100,
                "steps": []
              }
            ]
          },
          {
            "type": "random_pick",
            "branches": [
              {
                "weight": "${SHARE_WEIGHT}",
                "steps": [
                  {
                    "type": "if_element",
                    "by": "descriptionStartsWith",
                    "value": "Nút Chia sẻ.",
                    "timeout": 2,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "descriptionStartsWith",
                        "value": "Nút Chia sẻ.",
                        "timeout": 3
                      },
                      {
                        "type": "wait_stable",
                        "timeout": 4,
                        "stable_duration": 0.4
                      },
                      {
                        "type": "if_element",
                        "by": "text",
                        "value": "Chia sẻ ngay",
                        "timeout": 3,
                        "then": [
                          {
                            "type": "tap_selector",
                            "by": "text",
                            "value": "Chia sẻ ngay",
                            "timeout": 3
                          }
                        ],
                        "else": [
                          {
                            "type": "if_element",
                            "by": "text",
                            "value": "Share now",
                            "timeout": 2,
                            "then": [
                              {
                                "type": "tap_selector",
                                "by": "text",
                                "value": "Share now",
                                "timeout": 2
                              }
                            ],
                            "else": [
                              {
                                "type": "key",
                                "key": "back"
                              }
                            ]
                          }
                        ]
                      },
                      {
                        "type": "wait",
                        "seconds": 2
                      }
                    ]
                  }
                ]
              },
              {
                "weight": 100,
                "steps": []
              }
            ]
          },
          {
            "type": "set_variable",
            "name": "_S",
            "from_list": [
              1,
              1,
              2,
              2,
              3
            ]
          },
          {
            "type": "scroll_down",
            "repeats": "${_S}"
          },
          {
            "type": "set_variable",
            "name": "_READ",
            "from_list": [
              2,
              2.5,
              3,
              4,
              5
            ]
          },
          {
            "type": "wait",
            "seconds": "${_READ}"
          },
          {
            "type": "dismiss_popup",
            "retries": 1
          },
          {
            "type": "save_extraction",
            "data_var": "posts",
            "collection": "${SAVE_COLLECTION}",
            "platform": "facebook",
            "content_type": "group_post",
            "dedupe_field": "text",
            "tags": "group,crawl,${GROUP_1}"
          }
        ]
      },
      {
        "type": "save_extraction",
        "data_var": "posts",
        "collection": "${SAVE_COLLECTION}",
        "platform": "facebook",
        "content_type": "group_post",
        "dedupe_field": "text",
        "tags": "group,crawl,${GROUP_1}"
      },
      {
        "type": "key",
        "key": "back"
      },
      {
        "type": "key",
        "key": "back"
      },
      {
        "type": "wait",
        "seconds": 2
      },
      {
        "type": "wait_stable",
        "timeout": 5,
        "stable_duration": 0.5
      },
      {
        "type": "if_element",
        "by": "content-desc",
        "value": "Tìm kiếm",
        "timeout": 5,
        "then": [
          {
            "type": "tap_selector",
            "by": "content-desc",
            "value": "Tìm kiếm",
            "timeout": 4
          }
        ],
        "else": [
          {
            "type": "tap_ratio",
            "x": 0.87,
            "y": 0.035
          }
        ]
      },
      {
        "type": "wait_stable",
        "timeout": 4,
        "stable_duration": 0.4
      },
      {
        "type": "input_text",
        "text": "${GROUP_2}",
        "via": "u2"
      },
      {
        "type": "wait",
        "seconds": 2
      },
      {
        "type": "if_element",
        "by": "content-desc",
        "value": "${GROUP_2}",
        "timeout": 3,
        "then": [
          {
            "type": "tap_selector",
            "by": "content-desc",
            "value": "${GROUP_2}",
            "timeout": 3
          }
        ],
        "else": [
          {
            "type": "if_element",
            "by": "text",
            "value": "${GROUP_2}",
            "timeout": 3,
            "then": [
              {
                "type": "tap_selector",
                "by": "text",
                "value": "${GROUP_2}",
                "timeout": 3
              }
            ],
            "else": [
              {
                "type": "key",
                "key": "enter"
              },
              {
                "type": "wait",
                "seconds": 2
              },
              {
                "type": "if_element",
                "by": "text",
                "value": "Nhóm",
                "timeout": 3,
                "then": [
                  {
                    "type": "tap_selector",
                    "by": "text",
                    "value": "Nhóm",
                    "timeout": 3
                  }
                ],
                "else": [
                  {
                    "type": "if_element",
                    "by": "text",
                    "value": "Groups",
                    "timeout": 3,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "text",
                        "value": "Groups",
                        "timeout": 3
                      }
                    ]
                  }
                ]
              },
              {
                "type": "wait",
                "seconds": 2
              },
              {
                "type": "if_element",
                "by": "text",
                "value": "${GROUP_2}",
                "timeout": 5,
                "then": [
                  {
                    "type": "tap_selector",
                    "by": "text",
                    "value": "${GROUP_2}",
                    "timeout": 4
                  }
                ],
                "else": [
                  {
                    "type": "if_element",
                    "by": "content-desc",
                    "value": "${GROUP_2}",
                    "timeout": 3,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "content-desc",
                        "value": "${GROUP_2}",
                        "timeout": 3
                      }
                    ]
                  }
                ]
              }
            ]
          }
        ]
      },
      {
        "type": "wait_stable",
        "timeout": 6,
        "stable_duration": 0.5
      },
      {
        "type": "scroll_down",
        "repeats": 2
      },
      {
        "type": "wait_stable",
        "timeout": 3,
        "stable_duration": 0.4
      },
      {
        "type": "repeat",
        "count": "${SCROLLS_PER_GROUP}",
        "steps": [
          {
            "type": "extract",
            "strategy": "fb_posts",
            "expand_see_more": true
          },
          {
            "type": "random_pick",
            "branches": [
              {
                "weight": "${LIKE_WEIGHT}",
                "steps": [
                  {
                    "type": "if_element",
                    "by": "descriptionStartsWith",
                    "value": "Nút Thích.",
                    "timeout": 2,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "descriptionStartsWith",
                        "value": "Nút Thích.",
                        "timeout": 3
                      },
                      {
                        "type": "wait",
                        "seconds": 1
                      }
                    ]
                  }
                ]
              },
              {
                "weight": 100,
                "steps": []
              }
            ]
          },
          {
            "type": "random_pick",
            "branches": [
              {
                "weight": "${SHARE_WEIGHT}",
                "steps": [
                  {
                    "type": "if_element",
                    "by": "descriptionStartsWith",
                    "value": "Nút Chia sẻ.",
                    "timeout": 2,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "descriptionStartsWith",
                        "value": "Nút Chia sẻ.",
                        "timeout": 3
                      },
                      {
                        "type": "wait_stable",
                        "timeout": 4,
                        "stable_duration": 0.4
                      },
                      {
                        "type": "if_element",
                        "by": "text",
                        "value": "Chia sẻ ngay",
                        "timeout": 3,
                        "then": [
                          {
                            "type": "tap_selector",
                            "by": "text",
                            "value": "Chia sẻ ngay",
                            "timeout": 3
                          }
                        ],
                        "else": [
                          {
                            "type": "if_element",
                            "by": "text",
                            "value": "Share now",
                            "timeout": 2,
                            "then": [
                              {
                                "type": "tap_selector",
                                "by": "text",
                                "value": "Share now",
                                "timeout": 2
                              }
                            ],
                            "else": [
                              {
                                "type": "key",
                                "key": "back"
                              }
                            ]
                          }
                        ]
                      },
                      {
                        "type": "wait",
                        "seconds": 2
                      }
                    ]
                  }
                ]
              },
              {
                "weight": 100,
                "steps": []
              }
            ]
          },
          {
            "type": "set_variable",
            "name": "_S",
            "from_list": [
              1,
              1,
              2,
              2,
              3
            ]
          },
          {
            "type": "scroll_down",
            "repeats": "${_S}"
          },
          {
            "type": "set_variable",
            "name": "_READ",
            "from_list": [
              2,
              2.5,
              3,
              4,
              5
            ]
          },
          {
            "type": "wait",
            "seconds": "${_READ}"
          },
          {
            "type": "dismiss_popup",
            "retries": 1
          },
          {
            "type": "save_extraction",
            "data_var": "posts",
            "collection": "${SAVE_COLLECTION}",
            "platform": "facebook",
            "content_type": "group_post",
            "dedupe_field": "text",
            "tags": "group,crawl,${GROUP_2}"
          }
        ]
      },
      {
        "type": "save_extraction",
        "data_var": "posts",
        "collection": "${SAVE_COLLECTION}",
        "platform": "facebook",
        "content_type": "group_post",
        "dedupe_field": "text",
        "tags": "group,crawl,${GROUP_2}"
      },
      {
        "type": "key",
        "key": "back"
      },
      {
        "type": "key",
        "key": "back"
      },
      {
        "type": "wait",
        "seconds": 2
      },
      {
        "type": "wait_stable",
        "timeout": 5,
        "stable_duration": 0.5
      },
      {
        "type": "if_element",
        "by": "content-desc",
        "value": "Tìm kiếm",
        "timeout": 5,
        "then": [
          {
            "type": "tap_selector",
            "by": "content-desc",
            "value": "Tìm kiếm",
            "timeout": 4
          }
        ],
        "else": [
          {
            "type": "tap_ratio",
            "x": 0.87,
            "y": 0.035
          }
        ]
      },
      {
        "type": "wait_stable",
        "timeout": 4,
        "stable_duration": 0.4
      },
      {
        "type": "input_text",
        "text": "${GROUP_3}",
        "via": "u2"
      },
      {
        "type": "wait",
        "seconds": 2
      },
      {
        "type": "if_element",
        "by": "content-desc",
        "value": "${GROUP_3}",
        "timeout": 3,
        "then": [
          {
            "type": "tap_selector",
            "by": "content-desc",
            "value": "${GROUP_3}",
            "timeout": 3
          }
        ],
        "else": [
          {
            "type": "if_element",
            "by": "text",
            "value": "${GROUP_3}",
            "timeout": 3,
            "then": [
              {
                "type": "tap_selector",
                "by": "text",
                "value": "${GROUP_3}",
                "timeout": 3
              }
            ],
            "else": [
              {
                "type": "key",
                "key": "enter"
              },
              {
                "type": "wait",
                "seconds": 2
              },
              {
                "type": "if_element",
                "by": "text",
                "value": "Nhóm",
                "timeout": 3,
                "then": [
                  {
                    "type": "tap_selector",
                    "by": "text",
                    "value": "Nhóm",
                    "timeout": 3
                  }
                ],
                "else": [
                  {
                    "type": "if_element",
                    "by": "text",
                    "value": "Groups",
                    "timeout": 3,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "text",
                        "value": "Groups",
                        "timeout": 3
                      }
                    ]
                  }
                ]
              },
              {
                "type": "wait",
                "seconds": 2
              },
              {
                "type": "if_element",
                "by": "text",
                "value": "${GROUP_3}",
                "timeout": 5,
                "then": [
                  {
                    "type": "tap_selector",
                    "by": "text",
                    "value": "${GROUP_3}",
                    "timeout": 4
                  }
                ],
                "else": [
                  {
                    "type": "if_element",
                    "by": "content-desc",
                    "value": "${GROUP_3}",
                    "timeout": 3,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "content-desc",
                        "value": "${GROUP_3}",
                        "timeout": 3
                      }
                    ]
                  }
                ]
              }
            ]
          }
        ]
      },
      {
        "type": "wait_stable",
        "timeout": 6,
        "stable_duration": 0.5
      },
      {
        "type": "scroll_down",
        "repeats": 2
      },
      {
        "type": "wait_stable",
        "timeout": 3,
        "stable_duration": 0.4
      },
      {
        "type": "repeat",
        "count": "${SCROLLS_PER_GROUP}",
        "steps": [
          {
            "type": "extract",
            "strategy": "fb_posts",
            "expand_see_more": true
          },
          {
            "type": "random_pick",
            "branches": [
              {
                "weight": "${LIKE_WEIGHT}",
                "steps": [
                  {
                    "type": "if_element",
                    "by": "descriptionStartsWith",
                    "value": "Nút Thích.",
                    "timeout": 2,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "descriptionStartsWith",
                        "value": "Nút Thích.",
                        "timeout": 3
                      },
                      {
                        "type": "wait",
                        "seconds": 1
                      }
                    ]
                  }
                ]
              },
              {
                "weight": 100,
                "steps": []
              }
            ]
          },
          {
            "type": "random_pick",
            "branches": [
              {
                "weight": "${SHARE_WEIGHT}",
                "steps": [
                  {
                    "type": "if_element",
                    "by": "descriptionStartsWith",
                    "value": "Nút Chia sẻ.",
                    "timeout": 2,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "descriptionStartsWith",
                        "value": "Nút Chia sẻ.",
                        "timeout": 3
                      },
                      {
                        "type": "wait_stable",
                        "timeout": 4,
                        "stable_duration": 0.4
                      },
                      {
                        "type": "if_element",
                        "by": "text",
                        "value": "Chia sẻ ngay",
                        "timeout": 3,
                        "then": [
                          {
                            "type": "tap_selector",
                            "by": "text",
                            "value": "Chia sẻ ngay",
                            "timeout": 3
                          }
                        ],
                        "else": [
                          {
                            "type": "if_element",
                            "by": "text",
                            "value": "Share now",
                            "timeout": 2,
                            "then": [
                              {
                                "type": "tap_selector",
                                "by": "text",
                                "value": "Share now",
                                "timeout": 2
                              }
                            ],
                            "else": [
                              {
                                "type": "key",
                                "key": "back"
                              }
                            ]
                          }
                        ]
                      },
                      {
                        "type": "wait",
                        "seconds": 2
                      }
                    ]
                  }
                ]
              },
              {
                "weight": 100,
                "steps": []
              }
            ]
          },
          {
            "type": "set_variable",
            "name": "_S",
            "from_list": [
              1,
              1,
              2,
              2,
              3
            ]
          },
          {
            "type": "scroll_down",
            "repeats": "${_S}"
          },
          {
            "type": "set_variable",
            "name": "_READ",
            "from_list": [
              2,
              2.5,
              3,
              4,
              5
            ]
          },
          {
            "type": "wait",
            "seconds": "${_READ}"
          },
          {
            "type": "dismiss_popup",
            "retries": 1
          },
          {
            "type": "save_extraction",
            "data_var": "posts",
            "collection": "${SAVE_COLLECTION}",
            "platform": "facebook",
            "content_type": "group_post",
            "dedupe_field": "text",
            "tags": "group,crawl,${GROUP_3}"
          }
        ]
      },
      {
        "type": "save_extraction",
        "data_var": "posts",
        "collection": "${SAVE_COLLECTION}",
        "platform": "facebook",
        "content_type": "group_post",
        "dedupe_field": "text",
        "tags": "group,crawl,${GROUP_3}"
      },
      {
        "type": "key",
        "key": "back"
      },
      {
        "type": "key",
        "key": "back"
      },
      {
        "type": "wait",
        "seconds": 2
      },
      {
        "type": "wait_stable",
        "timeout": 5,
        "stable_duration": 0.5
      },
      {
        "type": "if_element",
        "by": "content-desc",
        "value": "Tìm kiếm",
        "timeout": 5,
        "then": [
          {
            "type": "tap_selector",
            "by": "content-desc",
            "value": "Tìm kiếm",
            "timeout": 4
          }
        ],
        "else": [
          {
            "type": "tap_ratio",
            "x": 0.87,
            "y": 0.035
          }
        ]
      },
      {
        "type": "wait_stable",
        "timeout": 4,
        "stable_duration": 0.4
      },
      {
        "type": "input_text",
        "text": "${GROUP_4}",
        "via": "u2"
      },
      {
        "type": "wait",
        "seconds": 2
      },
      {
        "type": "if_element",
        "by": "content-desc",
        "value": "${GROUP_4}",
        "timeout": 3,
        "then": [
          {
            "type": "tap_selector",
            "by": "content-desc",
            "value": "${GROUP_4}",
            "timeout": 3
          }
        ],
        "else": [
          {
            "type": "if_element",
            "by": "text",
            "value": "${GROUP_4}",
            "timeout": 3,
            "then": [
              {
                "type": "tap_selector",
                "by": "text",
                "value": "${GROUP_4}",
                "timeout": 3
              }
            ],
            "else": [
              {
                "type": "key",
                "key": "enter"
              },
              {
                "type": "wait",
                "seconds": 2
              },
              {
                "type": "if_element",
                "by": "text",
                "value": "Nhóm",
                "timeout": 3,
                "then": [
                  {
                    "type": "tap_selector",
                    "by": "text",
                    "value": "Nhóm",
                    "timeout": 3
                  }
                ],
                "else": [
                  {
                    "type": "if_element",
                    "by": "text",
                    "value": "Groups",
                    "timeout": 3,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "text",
                        "value": "Groups",
                        "timeout": 3
                      }
                    ]
                  }
                ]
              },
              {
                "type": "wait",
                "seconds": 2
              },
              {
                "type": "if_element",
                "by": "text",
                "value": "${GROUP_4}",
                "timeout": 5,
                "then": [
                  {
                    "type": "tap_selector",
                    "by": "text",
                    "value": "${GROUP_4}",
                    "timeout": 4
                  }
                ],
                "else": [
                  {
                    "type": "if_element",
                    "by": "content-desc",
                    "value": "${GROUP_4}",
                    "timeout": 3,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "content-desc",
                        "value": "${GROUP_4}",
                        "timeout": 3
                      }
                    ]
                  }
                ]
              }
            ]
          }
        ]
      },
      {
        "type": "wait_stable",
        "timeout": 6,
        "stable_duration": 0.5
      },
      {
        "type": "scroll_down",
        "repeats": 2
      },
      {
        "type": "wait_stable",
        "timeout": 3,
        "stable_duration": 0.4
      },
      {
        "type": "repeat",
        "count": "${SCROLLS_PER_GROUP}",
        "steps": [
          {
            "type": "extract",
            "strategy": "fb_posts",
            "expand_see_more": true
          },
          {
            "type": "random_pick",
            "branches": [
              {
                "weight": "${LIKE_WEIGHT}",
                "steps": [
                  {
                    "type": "if_element",
                    "by": "descriptionStartsWith",
                    "value": "Nút Thích.",
                    "timeout": 2,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "descriptionStartsWith",
                        "value": "Nút Thích.",
                        "timeout": 3
                      },
                      {
                        "type": "wait",
                        "seconds": 1
                      }
                    ]
                  }
                ]
              },
              {
                "weight": 100,
                "steps": []
              }
            ]
          },
          {
            "type": "random_pick",
            "branches": [
              {
                "weight": "${SHARE_WEIGHT}",
                "steps": [
                  {
                    "type": "if_element",
                    "by": "descriptionStartsWith",
                    "value": "Nút Chia sẻ.",
                    "timeout": 2,
                    "then": [
                      {
                        "type": "tap_selector",
                        "by": "descriptionStartsWith",
                        "value": "Nút Chia sẻ.",
                        "timeout": 3
                      },
                      {
                        "type": "wait_stable",
                        "timeout": 4,
                        "stable_duration": 0.4
                      },
                      {
                        "type": "if_element",
                        "by": "text",
                        "value": "Chia sẻ ngay",
                        "timeout": 3,
                        "then": [
                          {
                            "type": "tap_selector",
                            "by": "text",
                            "value": "Chia sẻ ngay",
                            "timeout": 3
                          }
                        ],
                        "else": [
                          {
                            "type": "if_element",
                            "by": "text",
                            "value": "Share now",
                            "timeout": 2,
                            "then": [
                              {
                                "type": "tap_selector",
                                "by": "text",
                                "value": "Share now",
                                "timeout": 2
                              }
                            ],
                            "else": [
                              {
                                "type": "key",
                                "key": "back"
                              }
                            ]
                          }
                        ]
                      },
                      {
                        "type": "wait",
                        "seconds": 2
                      }
                    ]
                  }
                ]
              },
              {
                "weight": 100,
                "steps": []
              }
            ]
          },
          {
            "type": "set_variable",
            "name": "_S",
            "from_list": [
              1,
              1,
              2,
              2,
              3
            ]
          },
          {
            "type": "scroll_down",
            "repeats": "${_S}"
          },
          {
            "type": "set_variable",
            "name": "_READ",
            "from_list": [
              2,
              2.5,
              3,
              4,
              5
            ]
          },
          {
            "type": "wait",
            "seconds": "${_READ}"
          },
          {
            "type": "dismiss_popup",
            "retries": 1
          },
          {
            "type": "save_extraction",
            "data_var": "posts",
            "collection": "${SAVE_COLLECTION}",
            "platform": "facebook",
            "content_type": "group_post",
            "dedupe_field": "text",
            "tags": "group,crawl,${GROUP_4}"
          }
        ]
      },
      {
        "type": "save_extraction",
        "data_var": "posts",
        "collection": "${SAVE_COLLECTION}",
        "platform": "facebook",
        "content_type": "group_post",
        "dedupe_field": "text",
        "tags": "group,crawl,${GROUP_4}"
      },
      {
        "type": "key",
        "key": "home"
      },
      {
        "type": "tap",
        "fallback": {
          "rx": 0.3639,
          "ry": 0.2474
        },
        "screen": {
          "package": "com.facebook.katana",
          "hash": "ab2b2f4f",
          "texts": [
            "23:49",
            "Tham gia nhóm OpenClaw VN",
            "Bạn viết gì đi...",
            "Cảm xúc",
            "Check in"
          ]
        }
      },
      {
        "type": "tap",
        "selector": {
          "by": "resource-id",
          "value": "com.facebook.katana:id/(name removed)"
        },
        "fallback": {
          "rx": 0.4037,
          "ry": 0.2332
        },
        "screen": {
          "package": "com.facebook.katana",
          "hash": "85cd25",
          "texts": [
            "23:51"
          ]
        }
      },
      {
        "type": "tap",
        "fallback": {
          "rx": 0.038,
          "ry": 0.0488
        },
        "screen": {
          "package": "com.facebook.katana",
          "hash": "6f7da4fd",
          "texts": [
            "23:52",
            "đã tham gia nhóm OpenClaw VN",
            "mời người khác tham gia OpenClaw VN",
            "Bạn viết gì đi..."
          ]
        }
      },
      {
        "type": "tap",
        "selector": {
          "by": "resource-id",
          "value": "com.facebook.katana:id/(name removed)"
        },
        "fallback": {
          "rx": 0.3685,
          "ry": 0.2228
        },
        "screen": {
          "package": "com.facebook.katana",
          "hash": "6e57c88d",
          "texts": [
            "23:52",
            "Kết quả tìm kiếm trong tab Tất cả, 1 trong số 7",
            "Kết quả tìm kiếm trong tab Mọi người, 2 trong số 7",
            "Kết quả tìm kiếm trong tab Nhóm, 3 trong số 7",
            "Kết quả tìm kiếm trong tab Sự kiện, 4 trong số 7"
          ]
        }
      }
    ]
  }